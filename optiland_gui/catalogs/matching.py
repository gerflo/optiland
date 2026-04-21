"""Helpers for linking imported catalog records across sources."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .importers.winlens_spd import WinLensAliasGroup
from .schema import CatalogLensRecord

_WINLENS_MANUFACTURER = "winlens library 2002"


@dataclass(slots=True)
class ResolvedWinLensAliases:
    """Alias context for one WinLens record."""

    exact_part_numbers: set[str]
    family_numbers: set[str]
    titles: list[str]
    materials: list[str]
    source_paths: list[str]


def build_winlens_match_map(
    winlens_records: list[CatalogLensRecord],
    existing_records: list[CatalogLensRecord],
    alias_groups: list[WinLensAliasGroup] | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Return ranked candidate links for each WinLens record."""
    links: dict[str, list[dict[str, object]]] = {}
    alias_index = _build_alias_index(alias_groups or [])
    for winlens_record in winlens_records:
        aliases = _resolve_aliases_for_record(winlens_record, alias_index)
        candidates: list[dict[str, object]] = []
        for candidate in existing_records:
            score, reasons = _score_winlens_candidate(winlens_record, candidate, aliases)
            if score <= 0:
                continue
            match_type = _classify_match_type(reasons, score)
            candidates.append(
                {
                    "catalog_id": candidate.catalog_id,
                    "manufacturer": candidate.manufacturer,
                    "part_number": candidate.part_number,
                    "product_name": candidate.product_name,
                    "score": score,
                    "match_type": match_type,
                    "confidence_percent": _estimate_confidence_percent(match_type, score),
                    "reasons": reasons,
                    "_candidate_family": _digits_only(candidate.part_number)[:6],
                    "_coating": candidate.coating or "",
                    "_category": candidate.category or "",
                    "_efl_mm": candidate.efl_mm,
                    "_diameter_mm": candidate.diameter_mm,
                }
            )
        if candidates:
            _promote_coating_variant_families(winlens_record, candidates, aliases)
            _promote_strong_family_matches(winlens_record, candidates)
            ranked = sorted(
                candidates,
                key=lambda item: (
                    0 if item.get("match_type") == "confirmed" else 1,
                    -int(item["score"]),
                    str(item["catalog_id"]),
                ),
            )[:5]
            links[winlens_record.catalog_id] = [
                {key: value for key, value in item.items() if not str(key).startswith("_")}
                for item in ranked
            ]
    return links


def _score_winlens_candidate(
    winlens_record: CatalogLensRecord,
    candidate: CatalogLensRecord,
    aliases: ResolvedWinLensAliases | None,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    winlens_part = _compact_token(winlens_record.part_number)
    candidate_part = _compact_token(candidate.part_number)
    winlens_digits = _digits_only(winlens_record.part_number)
    candidate_digits = _digits_only(candidate.part_number)
    candidate_family = candidate_digits[:6] if len(candidate_digits) >= 6 else ""

    if winlens_part and winlens_part == candidate_part:
        score += 120
        reasons.append("exact compact part number")
    if winlens_digits and candidate_digits:
        if winlens_digits == candidate_digits:
            score += 110
            reasons.append("exact numeric part number")
        elif min(len(winlens_digits), len(candidate_digits)) >= 6:
            if winlens_digits in candidate_digits or candidate_digits in winlens_digits:
                score += 95
                reasons.append("numeric part number overlap")
    if aliases is not None:
        if candidate_digits and candidate_digits in aliases.exact_part_numbers:
            score += 220
            reasons.append("WinLens alias map exact")
        elif candidate_family and candidate_family in aliases.family_numbers:
            score += 170
            reasons.append("WinLens alias family")
        alias_title_hit = any(
            _compact_token(title) == _compact_token(candidate.product_name)
            for title in aliases.titles
            if title
        )
        if alias_title_hit:
            score += 12
            reasons.append("matching WinLens alias title")
        if (
            candidate.material_summary
            and any(
                material.casefold() in candidate.material_summary.casefold()
                for material in aliases.materials
            )
        ):
            score += 10
            reasons.append("matching WinLens alias material")

    if _is_linos_standard_system(winlens_record) and candidate.manufacturer.casefold() == "excelitas linos":
        score += 15
        reasons.append("LINOS family hint")

    if _numbers_close(winlens_record.efl_mm, candidate.efl_mm, tolerance=0.5):
        score += 15
        reasons.append("matching efl")
    if _numbers_close(winlens_record.diameter_mm, candidate.diameter_mm, tolerance=0.5):
        score += 15
        reasons.append("matching diameter")
    if (
        winlens_record.category
        and candidate.category
        and winlens_record.category.casefold() == candidate.category.casefold()
    ):
        score += 10
        reasons.append("matching category")
    if (
        winlens_record.material_summary
        and candidate.material_summary
        and winlens_record.material_summary.casefold() == candidate.material_summary.casefold()
    ):
        score += 8
        reasons.append("matching material")

    return score, reasons


def _promote_coating_variant_families(
    winlens_record: CatalogLensRecord,
    candidates: list[dict[str, object]],
    aliases: ResolvedWinLensAliases | None,
) -> None:
    if aliases is None:
        return
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for candidate in candidates:
        reasons = [str(reason) for reason in candidate.get("reasons", [])]
        family = str(candidate.get("_candidate_family", ""))
        if "WinLens alias family" not in reasons and "WinLens alias map exact" not in reasons:
            continue
        if not family:
            continue
        if family not in aliases.family_numbers and _digits_only(str(candidate.get("part_number", ""))) not in aliases.exact_part_numbers:
            continue
        if not _numbers_close(winlens_record.efl_mm, _float_or_none(candidate.get("_efl_mm")), tolerance=0.5):
            continue
        if not _numbers_close(
            winlens_record.diameter_mm,
            _float_or_none(candidate.get("_diameter_mm")),
            tolerance=0.5,
        ):
            continue
        category = str(candidate.get("_category", "")).casefold()
        if category and winlens_record.category and category != winlens_record.category.casefold():
            continue
        key = (
            str(candidate.get("manufacturer", "")).casefold(),
            family,
            category,
        )
        grouped.setdefault(key, []).append(candidate)

    for group in grouped.values():
        if len(group) < 2:
            continue
        coatings = {
            str(candidate.get("_coating", "")).strip().casefold()
            for candidate in group
        }
        if len(coatings) < 2:
            continue
        for candidate in group:
            reasons = [str(reason) for reason in candidate.get("reasons", [])]
            if "WinLens coating-blind family propagation" not in reasons:
                reasons.append("WinLens coating-blind family propagation")
            candidate["reasons"] = reasons
            candidate["match_type"] = "confirmed"


def _promote_strong_family_matches(
    winlens_record: CatalogLensRecord,
    candidates: list[dict[str, object]],
) -> None:
    grouped: dict[str, list[dict[str, object]]] = {}
    for candidate in candidates:
        reasons = [str(reason) for reason in candidate.get("reasons", [])]
        family = str(candidate.get("_candidate_family", ""))
        if not family:
            continue
        if "numeric part number overlap" not in reasons:
            continue
        if "LINOS family hint" not in reasons:
            continue
        if "matching efl" not in reasons:
            continue
        if len(_digits_only(winlens_record.part_number)) < 6:
            continue
        grouped.setdefault(family, []).append(candidate)

    if not grouped:
        return
    ranked_groups = sorted(
        grouped.items(),
        key=lambda item: max(int(candidate.get("score", 0)) for candidate in item[1]),
        reverse=True,
    )
    best_family, best_group = ranked_groups[0]
    best_score = max(int(candidate.get("score", 0)) for candidate in best_group)
    second_score = (
        max(int(candidate.get("score", 0)) for candidate in ranked_groups[1][1])
        if len(ranked_groups) > 1
        else -1
    )
    if best_score < 120:
        return
    if second_score >= best_score:
        return

    for candidate in best_group:
        reasons = [str(reason) for reason in candidate.get("reasons", [])]
        if "WinLens strong family match" not in reasons:
            reasons.append("WinLens strong family match")
        candidate["reasons"] = reasons
        candidate["match_type"] = "confirmed"


def _is_linos_standard_system(record: CatalogLensRecord) -> bool:
    source_path = (record.source.source_path or "").casefold()
    return "linos_standard_systems" in source_path


def _compact_token(value: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", value.casefold())


def _digits_only(value: str) -> str:
    return re.sub(r"[^0-9]+", "", value)


def _numbers_close(first: float | None, second: float | None, *, tolerance: float) -> bool:
    if first is None or second is None:
        return False
    return abs(float(first) - float(second)) <= tolerance


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_match_type(reasons: list[str], score: int) -> str:
    if "WinLens alias map exact" in reasons:
        return "confirmed"
    if "exact compact part number" in reasons and "exact numeric part number" in reasons:
        return "confirmed"
    if "exact numeric part number" in reasons and score >= 140:
        return "confirmed"
    return "candidate"


def _estimate_confidence_percent(match_type: str, score: int) -> int:
    if match_type == "confirmed":
        return 100
    return max(0, min(95, int(score)))


def _build_alias_index(
    alias_groups: list[WinLensAliasGroup],
) -> dict[str, list[WinLensAliasGroup]]:
    index: dict[str, list[WinLensAliasGroup]] = {}
    for group in alias_groups:
        for token in (*group.part_numbers, *group.family_numbers):
            index.setdefault(token, []).append(group)
    return index


def _resolve_aliases_for_record(
    winlens_record: CatalogLensRecord,
    alias_index: dict[str, list[WinLensAliasGroup]],
) -> ResolvedWinLensAliases | None:
    tokens = {
        _digits_only(winlens_record.part_number),
        _digits_only(winlens_record.catalog_id),
    }
    winlens_digits = _digits_only(winlens_record.part_number)
    if len(winlens_digits) >= 6:
        tokens.add(winlens_digits[:6])
    groups: list[WinLensAliasGroup] = []
    seen: set[tuple[str, ...]] = set()
    for token in tokens:
        if not token:
            continue
        for group in alias_index.get(token, []):
            key = tuple(group.part_numbers)
            if key in seen:
                continue
            seen.add(key)
            groups.append(group)
    if not groups:
        return None
    exact_part_numbers = {token for group in groups for token in group.part_numbers}
    family_numbers = {token for group in groups for token in group.family_numbers}
    titles = [group.title for group in groups if group.title]
    materials = [material for group in groups for material in group.materials]
    source_paths = [group.source_path for group in groups]
    return ResolvedWinLensAliases(
        exact_part_numbers=exact_part_numbers,
        family_numbers=family_numbers,
        titles=titles,
        materials=materials,
        source_paths=source_paths,
    )
