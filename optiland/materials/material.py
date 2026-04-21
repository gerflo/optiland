"""Material

This module contains the Material class, which represents a generic material
used in the Optiland system. This class identifies the correct material given
the material name and (optionally) the reference, which is generally the
manufacturer name or the author name. This is the primary material class used
to define the optical properties of a material (or glass) in Optiland.

Kramer Harrison, 2024
"""

# import pkg_resources
from __future__ import annotations

from importlib import resources
import re
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

from optiland.materials.material_file import MaterialFile

_WINLENS_N_PREFIX_RE = r"^([A-Z]+)N([0-9][A-Z0-9]*)$"
_WINLENS_ALIAS_ENTRY_RE = re.compile(
    rb"([A-Z][A-Z0-9-]{2,20})\s{8,}[\x00-\x20\xff\xfe]{0,4}(\[[A-Za-z]+\]|[A-Za-z][A-Za-z ]{2,20})\s{8,}",
)
_VERIFIED_WINLENS_ALIAS_MANUFACTURERS = {"schott"}


class Material(MaterialFile):
    """Represents a generic material used in the Optiland system.
    This class identifies the correct material given the material name and
    (optionally) the reference, which is generally the manufacturer name or
    the author name.

    Note:
        The material database is stored in the file `catalog_nk.csv` in the
        `database` directory. This contains the names, references, and
        filenames of the materials.

    Args:
        name (str): The name of the material to search for.
        reference (str, optional): The reference for the material, typically
            the manufacturer or author name. This helps disambiguate materials
            with similar names. Defaults to None.
        robust_search (bool, optional): If True, the search attempts to find the
            closest match even if an exact match isn't found, and returns the
            first one based on similarity scoring. If False, an error is raised
            if multiple close matches are found. Defaults to True.
        min_wavelength (float, optional): Minimum wavelength in microns for
            filtering materials based on their valid range. Defaults to None.
        max_wavelength (float, optional): Maximum wavelength in microns for
            filtering materials based on their valid range. Defaults to None.

    Attributes:
        name (str): The name of the material.
        reference (str): The reference for the material.

    """

    _df = None
    _filename = str(resources.files("optiland.database").joinpath("catalog_nk.csv"))
    _winlens_alias_entries: list[tuple[str, str | None]] | None = None

    def __init__(
        self,
        name,
        reference=None,
        robust_search=True,
        warn_on_inexact=True,
        min_wavelength=None,
        max_wavelength=None,
        propagation_model=None,
    ):
        self.name = name
        self.reference = reference
        self.robust = robust_search
        self.warn_on_inexact = warn_on_inexact
        self.min_wavelength = min_wavelength
        self.max_wavelength = max_wavelength
        file, self.material_data = self._retrieve_file()
        super().__init__(file, propagation_model=propagation_model)

    @classmethod
    def _load_dataframe(cls):
        """Load the DataFrame if not yet loaded."""
        if cls._df is None:
            frames = [pd.read_csv(cls._filename)]
            for extra_file in cls._extra_catalog_csv_files():
                try:
                    frames.append(pd.read_csv(extra_file))
                except (FileNotFoundError, EmptyDataError):
                    continue
            cls._df = pd.concat(frames, ignore_index=True)
        return cls._df

    @classmethod
    def _extra_catalog_csv_files(cls) -> list[Path]:
        candidate = Path(cls._filename).with_name("catalog_nk_winlens.csv")
        return [candidate] if candidate.is_file() else []

    @staticmethod
    def _levenshtein_distance(s1, s2):
        """Calculates the Levenshtein distance between two strings.

        Args:
            s1 (str): The first string.
            s2 (str): The second string.

        Returns:
            int: The Levenshtein distance between the two strings.

        """
        # Initialize matrix of zeros
        rows = len(s1) + 1
        cols = len(s2) + 1
        distance_matrix = [[0 for _ in range(cols)] for _ in range(rows)]

        # Populate matrix with initial values
        for i in range(1, rows):
            distance_matrix[i][0] = i
        for j in range(1, cols):
            distance_matrix[0][j] = j

        # Calculate the distance
        for i in range(1, rows):
            for j in range(1, cols):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                distance_matrix[i][j] = min(
                    distance_matrix[i - 1][j] + 1,
                    distance_matrix[i][j - 1] + 1,
                    distance_matrix[i - 1][j - 1] + cost,
                )

        return distance_matrix[-1][-1]

    def _find_material_matches(self, df):
        """Finds material matches in a DataFrame based on the given name and
        reference.

        Args:
            df (pandas.DataFrame): The DataFrame containing the materials.

        Returns:
            pandas.DataFrame: A DataFrame containing materials that match the
            search criteria, sorted by similarity score. Returns an empty
            DataFrame if no potential matches are found.

        """
        candidates = self._material_name_candidates(self.name, self.reference)
        lowered_candidates = [candidate.lower() for candidate in candidates]

        # Filter rows where input string is substring of category_name or name
        mask = pd.Series(False, index=df.index)
        for name in lowered_candidates:
            mask = mask | (
                df["category_name"].str.lower().str.contains(name)
                | df["name"].str.lower().str.contains(name)
                | df["filename_no_ext"].str.lower().str.contains(name)
            )
        dfi = df[mask].copy()

        # If reference given, filter rows non-matching rows
        if self.reference:
            reference = self.reference.lower()
            dfi = dfi[
                dfi["category_name"].str.lower().str.contains(reference)
                | dfi["category_name_full"].str.lower().str.contains(reference)
                | dfi["reference"].str.lower().str.contains(reference)
                | dfi["name"].str.lower().str.contains(reference)
                | dfi["filename"].str.lower().str.contains(reference)
            ]

        # Filter rows based on wavelength range
        if self.min_wavelength:
            dfi = dfi[
                (dfi["min_wavelength"] <= self.min_wavelength)
                & (dfi["max_wavelength"] >= self.min_wavelength)
            ]
        if self.max_wavelength:
            dfi = dfi[
                (dfi["min_wavelength"] <= self.max_wavelength)
                & (dfi["max_wavelength"] >= self.max_wavelength)
            ]

        # If no rows match, return an empty DataFrame
        if dfi.empty:
            return pd.DataFrame()

        exact_mask = pd.Series(False, index=dfi.index)
        exact_name_values = {
            candidate.casefold()
            for candidate in candidates
            if candidate and candidate.strip()
        }
        if exact_name_values:
            exact_mask = (
                dfi["category_name"].fillna("").str.casefold().isin(exact_name_values)
                | dfi["name"].fillna("").str.casefold().isin(exact_name_values)
                | dfi["filename_no_ext"].fillna("").str.casefold().isin(exact_name_values)
            )
        if exact_mask.any():
            dfi = dfi[exact_mask].copy()

        # Calculate similarity scores using Levenshtein distance
        dfi["similarity_score"] = dfi.apply(
            lambda row: min(
                min(
                    self._levenshtein_distance(name, row["category_name"].lower()),
                    self._levenshtein_distance(name, row["name"].lower()),
                    self._levenshtein_distance(name, row["filename_no_ext"].lower()),
                )
                for name in lowered_candidates
            ),
            axis=1,
        )

        # Sort by similarity score in ascending order
        dfi = dfi.sort_values(by="similarity_score").reset_index(drop=True)

        # Warning if no exact matches found
        if self.warn_on_inexact and dfi["similarity_score"].iloc[0] > 0:
            print(
                f"Warning: No exact matches found for material {self.name}. "
                "Material may be invalid.",
            )

        return dfi

    @classmethod
    def _material_name_candidates(
        cls,
        name: str,
        reference: str | None = None,
    ) -> list[str]:
        """Return ordered search candidates for exact and WinLens-style aliases."""
        cleaned = str(name or "").strip()
        if not cleaned:
            return [cleaned]

        candidates: list[str] = []
        seen: set[str] = set()

        def add(candidate: str) -> None:
            normalized = candidate.strip()
            if not normalized:
                return
            key = normalized.casefold()
            if key in seen:
                return
            seen.add(key)
            candidates.append(normalized)

        add(cleaned)
        add(cleaned.replace(" ", ""))

        compact_upper = cleaned.replace(" ", "").upper()
        add(compact_upper)

        match = re.match(_WINLENS_N_PREFIX_RE, compact_upper)
        if match and "-" not in compact_upper:
            add(f"N-{match.group(1)}{match.group(2)}")

        for alias in cls._lookup_winlens_alias_candidates(cleaned, reference):
            add(alias)

        return candidates

    @classmethod
    def _lookup_winlens_alias_candidates(
        cls,
        name: str,
        reference: str | None,
    ) -> list[str]:
        entries = cls._load_winlens_alias_entries()
        if not entries:
            return []
        name_key = cls._normalize_material_alias_key(name)
        if not name_key:
            return []

        reference_key = cls._normalize_reference_key(reference)
        candidates: list[str] = []
        seen: set[str] = set()
        verified_targets = cls._verified_winlens_alias_targets(name, reference)
        if not verified_targets:
            return []

        def add(candidate: str) -> None:
            normalized = candidate.strip()
            if not normalized:
                return
            key = normalized.casefold()
            if key in seen:
                return
            seen.add(key)
            candidates.append(normalized)

        for alias_name, alias_reference in entries:
            if cls._normalize_material_alias_key(alias_name) != name_key:
                continue
            if reference_key and cls._normalize_reference_key(alias_reference) != reference_key:
                continue
            if alias_name in verified_targets:
                add(alias_name)

        if reference_key:
            return candidates

        for alias_name, alias_reference in entries:
            if cls._normalize_material_alias_key(alias_name) != name_key:
                continue
            if alias_name in verified_targets:
                add(alias_name)

        return candidates

    @classmethod
    def _load_winlens_alias_entries(cls) -> list[tuple[str, str | None]]:
        if cls._winlens_alias_entries is None:
            entries: list[tuple[str, str | None]] = []
            seen: set[tuple[str, str | None]] = set()
            for path in cls._find_winlens_glassplus_files():
                for entry in cls._extract_winlens_alias_entries(path.read_bytes()):
                    if entry in seen:
                        continue
                    seen.add(entry)
                    entries.append(entry)
            cls._winlens_alias_entries = entries
        return cls._winlens_alias_entries

    @staticmethod
    def _find_winlens_glassplus_files() -> list[Path]:
        filenames = ("stglassplus.dat", "spglassplus.dat")
        paths: list[Path] = []
        seen: set[Path] = set()
        for base in (Path.cwd(), *Path.cwd().parents):
            candidate_dir = base / "WinLens Library 2002" / "WinLens3DBasic"
            for filename in filenames:
                candidate = candidate_dir / filename
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                paths.append(resolved)
        return paths

    @classmethod
    def _extract_winlens_alias_entries(cls, data: bytes) -> list[tuple[str, str | None]]:
        entries: list[tuple[str, str | None]] = []
        seen: set[tuple[str, str | None]] = set()
        for match in _WINLENS_ALIAS_ENTRY_RE.finditer(data):
            name = match.group(1).decode("latin1", "ignore").strip()
            reference = match.group(2).decode("latin1", "ignore").strip()
            normalized_reference = cls._normalize_reference_value(reference)
            entry = (name, normalized_reference)
            if entry in seen:
                continue
            seen.add(entry)
            entries.append(entry)
        return entries

    @staticmethod
    def _normalize_material_alias_key(name: str | None) -> str:
        compact = re.sub(r"[^A-Z0-9]", "", str(name or "").upper())
        match = re.match(_WINLENS_N_PREFIX_RE, compact)
        if match:
            return f"N{match.group(1)}{match.group(2)}"
        return compact

    @staticmethod
    def _normalize_reference_value(reference: str | None) -> str | None:
        cleaned = str(reference or "").strip()
        if not cleaned or cleaned.casefold() == "[generic]":
            return None
        return cleaned

    @staticmethod
    def _normalize_reference_key(reference: str | None) -> str | None:
        cleaned = str(reference or "").strip()
        if not cleaned:
            return None
        return cleaned.casefold()

    @classmethod
    def _verified_winlens_alias_targets(
        cls,
        name: str,
        reference: str | None,
    ) -> set[str]:
        """Return alias candidates allowed by the strict no-review import policy."""
        reference_key = cls._normalize_reference_key(reference)
        if reference_key not in _VERIFIED_WINLENS_ALIAS_MANUFACTURERS:
            return set()

        compact_upper = re.sub(r"[^A-Z0-9]", "", str(name or "").upper())
        targets: set[str] = set()

        if reference_key == "schott":
            match = re.match(_WINLENS_N_PREFIX_RE, compact_upper)
            if match:
                targets.add(f"N-{match.group(1)}{match.group(2)}")
            if compact_upper.startswith("N") and len(compact_upper) > 2:
                targets.add(f"N-{compact_upper[1:]}")

        return {
            target
            for target in targets
            if cls._catalog_contains_material(target, reference)
        }

    @classmethod
    def resolve_winlens_safe_name(
        cls,
        name: str,
        reference: str | None,
    ) -> str | None:
        """Return a canonical safe target for WinLens material import.

        Only exact manufacturer/name matches or officially verified alias
        transforms are accepted here. This intentionally excludes fuzzy
        matching so non-verifiable WinLens materials stay unresolved.
        """
        direct_targets = cls._catalog_exact_targets(name, reference)
        if len(direct_targets) == 1:
            return next(iter(direct_targets))

        alias_targets = cls._verified_winlens_alias_targets(name, reference)
        if len(alias_targets) == 1:
            return next(iter(alias_targets))

        return None

    @classmethod
    def _catalog_contains_material(cls, name: str, reference: str | None) -> bool:
        df = cls._load_dataframe()
        name_key = cls._normalize_material_alias_key(name)
        reference_key = cls._normalize_reference_key(reference)
        if not name_key or not reference_key:
            return False

        refs = (
            df["reference"].fillna("").str.casefold() == reference_key
        ) | (
            df["category_name"].fillna("").str.casefold() == reference_key
        ) | (
            df["category_name_full"].fillna("").str.casefold() == reference_key
        )
        names = df["filename_no_ext"].fillna("").apply(cls._normalize_material_alias_key) == name_key
        return bool((refs & names).any())

    @classmethod
    def _catalog_exact_targets(cls, name: str, reference: str | None) -> set[str]:
        df = cls._load_dataframe()
        raw_name = str(name or "").strip()
        reference_key = cls._normalize_reference_key(reference)
        if not raw_name or not reference_key:
            return set()

        refs = (
            df["reference"].fillna("").str.casefold() == reference_key
        ) | (
            df["category_name"].fillna("").str.casefold() == reference_key
        ) | (
            df["category_name_full"].fillna("").str.casefold() == reference_key
        )
        exact_name = df["name"].fillna("").str.casefold() == raw_name.casefold()
        exact_filename = df["filename_no_ext"].fillna("").str.casefold() == raw_name.casefold()
        matches = df[refs & (exact_name | exact_filename)]
        return {
            str(value).strip()
            for value in matches["filename_no_ext"].dropna().tolist()
            if str(value).strip()
        }

    @classmethod
    def _catalog_has_exact_manufacturer_material(
        cls,
        name: str,
        manufacturer: str | None,
    ) -> bool:
        df = cls._load_dataframe()
        raw_name = str(name or "").strip()
        manufacturer_key = cls._normalize_reference_key(manufacturer)
        if not raw_name or not manufacturer_key:
            return False

        exact_name = (
            df["name"].fillna("").str.casefold() == raw_name.casefold()
        ) | (
            df["filename_no_ext"].fillna("").str.casefold() == raw_name.casefold()
        )
        manufacturer_mask = (
            df["reference"].fillna("").str.casefold().str.contains(manufacturer_key)
            | df["category_name"].fillna("").str.casefold().str.contains(manufacturer_key)
            | df["category_name_full"].fillna("").str.casefold().str.contains(manufacturer_key)
            | df["filename"].fillna("").str.replace("\\", "/", regex=False).str.casefold().str.contains(f"/{manufacturer_key}/")
        )
        return bool((exact_name & manufacturer_mask).any())

    def _raise_material_error(self, no_matches=False, multiple_matches=False):
        """Raises an error if no matches or multiple matches are found for the
        material.

        Args:
            no_matches (bool): Indicates if no matches were found.
            multiple_matches (bool): Indicates if multiple matches were found.

        Raises:
            ValueError: If no matches or multiple matches are found for the
                material.

        """
        if no_matches:
            message = f"No matches found for material {self.name}"
        elif multiple_matches:
            message = f"Multiple matches found for material {self.name}"
        else:
            message = f"Error finding material {self.name}"

        if self.reference:
            message += f" with reference {self.reference}"

        if self.min_wavelength or self.max_wavelength:
            wavelength_range = f"({self.min_wavelength}, {self.max_wavelength}) µm"
            message += f" within wavelength range {wavelength_range}"

        raise ValueError(message)

    def _retrieve_file(self):
        """Retrieves the file path for the material based on the given criteria.

        Returns:
            tuple[str, dict]: A tuple containing:
                - The full file path to the material data file.
                - A dictionary containing the material's metadata from the catalog.

        Raises:
            ValueError: If no matches are found for the material.
            ValueError: If multiple matches are found for the material.

        """
        df = self._load_dataframe()
        filtered_df = self._find_material_matches(df)

        if filtered_df.empty:
            self._raise_material_error(no_matches=True)

        if len(filtered_df) > 1 and not self.robust:
            self._raise_material_error(multiple_matches=True)

        material_data = filtered_df.loc[0].to_dict()
        filename = filtered_df.loc[0, "filename"]

        full_filename = str(
            resources.files("optiland.database").joinpath("data-nk", filename),
        )

        return full_filename, material_data

    def to_dict(self):
        """Converts the material to a dictionary.

        Returns:
            dict: A dictionary representation of the Material instance's
            configuration, not the material data itself.

        """
        material_dict = super().to_dict()
        material_dict.update(
            {
                "name": self.name,
                "reference": self.reference,
                "robust_search": self.robust,
                "warn_on_inexact": self.warn_on_inexact,
                "min_wavelength": self.min_wavelength,
                "max_wavelength": self.max_wavelength,
            },
        )

        return material_dict

    @classmethod
    def from_dict(cls, data):
        """Creates a material from a dictionary representation.

        Args:
            data (dict): The dictionary representation of the material.

        Returns:
            Material: The material created from the dictionary.

        """
        if "name" not in data:
            raise ValueError("Missing required key: name")

        return cls(
            data["name"],
            data.get("reference", None),
            data.get("robust_search", True),
            data.get("min_wavelength", None),
            data.get("max_wavelength", None),
            # propagation_model is handled by MaterialFile.from_dict
        )
