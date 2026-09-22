.. _gui_quickstart:

Optiland GUI Quickstart
=======================

Welcome to the Optiland Graphical User Interface (GUI)! This guide will help you get started with the basic features for interactive optical design and analysis.

What can the GUI do?
--------------------

The Optiland GUI provides a user-friendly way to:

*   Create new optical systems from scratch.
*   Save and load optical systems in Optiland's native JSON format.
*   Visually inspect optical systems in 2D and 3D.
*   Edit system parameters, including surface data (radius, thickness, material, etc.), aperture, field points, and wavelengths.
*   Run various optical analyses (e.g., ray fans, spot diagrams, MTF).
*   View analysis results graphically.
*   Access an embedded Python terminal for advanced scripting and automation.

Note that not all features available in the Optiland Python API are exposed in the GUI, but many common tasks are easily accessible. New features are continuously being added,
so keep an eye on future updates for more functionality.

Launching the GUI
-----------------

You can launch the Optiland GUI in a couple of ways:

1.  **From the command line (recommended for most users):**
    Open your terminal or console and type:

    .. code-block:: bash

       optiland

    This command will start the main application window. If you have installed Optiland correctly, this should work seamlessly.

2.  **From Python (useful for development or troubleshooting):**
    Open your terminal or console and type:

    .. code-block:: bash

       python -m optiland_gui.run_gui

Main Interface Components
-------------------------

When you first open the Optiland GUI, you'll see a main window containing several panels. Here's a brief overview:

.. image:: _static/gui_overview.png
   :alt: Optiland GUI Overview
   :align: center

*   **Main Window**: Contains the main menu bar (File, Edit, View, Tools, Help), toolbars for quick actions, and manages the different panels.
*   **Lens Data Editor**: This is where you view and modify the surface-by-surface data of your optical system, such as radius, thickness, material, conic constants, and semi-diameters. Changes made here are reflected in other panels. The thickness of the object row is the object distance; type ``inf`` for an object at infinity. A disabled surface is left out of the drawn and traced system while every other surface keeps its place.

    .. image:: _static/gui_lens_data_editor.png
       :alt: Viewer Panel (2D/3D)
       :align: center
       :width: 600px

*   **System Viewer**: This panel provides visual representations of your optical system, one per tab.

    *   **System**: The whole multi-axis system (see *System View* below). It is the first tab.
    *   **2D Layout**: Shows a 2D cross-section of the lens, with options to display rays.
    *   **3D Layout**: Renders a 3D model of the system (if VTK is installed and working).
    *   **Sag**: The sag of one surface.

    Aperture markers are purple: the stop bright, every other physical aperture darker (settings *Show Apertures* in 2D, *Stop Aperture* / *Other Apertures* in the 3D toolbar). **Mask stops** (the *Circular Mask* and *Annular Mask* aperture types, e.g. anti-reflex dots) are red: the 2D layout draws their blocking disk or ring as a thick bar on the surface, next to the marker of their clear radius; the 3D layout draws the disk or ring on the surface and a ring beyond the clear radius. Masks have their own switch, on by default, so they show even with the aperture markers off: *Show Masks* in the 2D settings, *Masks* in the 3D toolbar. A mask on the stop surface keeps the stop's purple edge. The central disk an *Annular Aperture* blocks is drawn red in the same way, under the same switch; its clear edge stays an aperture marker.

    Every tab has a small button next to its title that shows it in a separate window, for instance on a second screen. Closing that window puts the tab back in its old place. The last tab left in the System Viewer has no such button, so the viewer is never empty. The settings of the 2D and 3D layouts appear beside the layout you work in, docked or in its own window. Optiland remembers where each window was: the next session reopens the detached tabs where you left them, and a tab detached again opens where its window was last. *Dock All Windows* and *Reset Window Layout* put every tab back into the System Viewer.

    .. image:: _static/gui_viewer_panel.png
       :alt: Viewer Panel (2D/3D)
       :align: center
       :width: 600px

*   **Analysis Panel**: Allows you to select, configure, and run various optical analyses. Results are typically displayed as plots within this panel. Note that you can run several analyses, each of which can be accessed using the numbered tabs on the right sidebar.

    .. image:: _static/gui_analysis_panel.png
       :alt: Analysis Panel
       :align: center
       :width: 600px

*   **System View** (the *System* tab of the System Viewer; the *System* button in the sidebar brings it to the front): Systems with several optical axes (a fundus camera: observation through the hole of a fold mirror, ring illumination reflected by it) are ``*.olsys`` files. The view draws the folded system with recorded ray paths, one irradiance map per detector and the energy balance; traces run on a background thread. The layout zooms with the mouse wheel around the cursor, pans with a left drag, and *Fit* (or a double click) shows everything again; the view keeps your zoom across traces and rebuilds. Every system folded with ``tools/merge_optic_paths.py`` carries its named **optical paths**: pick one in the *Path* pull-down, or click one of its elements in the layout, and that path's sequential design is loaded into the Lens Data Editor, the 2D layout, the analyses and the optimizer. Edits made there rebuild the system after a short pause (the trace result is cleared until you trace again); *Rename...* names a path. The system is the document: *File → Save* writes every path and the scene to a ``*.olsys`` file (with the file-format version and the GUI version that saved it), and *File → Export → To Optiland JSON* writes one path, chosen in a dialog, as a plain sequential design file. A sequential ``*.json`` opened through *File → Open* becomes path 1 of a new system; when the open system already has several paths, a dialog asks which one the file fills (the first is preselected) or whether to start a new system. A ``*.olsys`` file opened through *File → Open* or the recent-files list lands in this view with its first path active; two sample scenes (a 50:50 beam splitter, a side illumination with imaging in transmission) are bundled.

*   **System Properties Panel**: Manage system-wide settings that are not tied to individual surfaces. This includes:

    *   **Aperture**: Define the system aperture (e.g., Entrance Pupil Diameter, F-number).
    *   **Fields**: Set up field points for analysis.
    *   **Wavelengths**: Define the wavelengths and their weights for calculations.
    *   **Layout**: *Z origin* chooses where z = 0 lies on the z axis of the 2D layout and in its cursor readout: at surface 1 (Optiland's convention, a finite object sits at z = -object distance) or at the object, e.g. the light source of an illumination path. Only the displayed coordinate changes; the setting is saved with the design. An object at infinity always uses surface 1.

    .. image:: _static/gui_system_properties.png
       :alt: System Properties Panel
       :align: center
       :width: 600px

*   **Sidebar**: Located on the left, it provides quick navigation to show/hide the main panels like Lens Editor, Viewer, Analysis, etc.
*   **Python Terminal** (View > Python Terminal): An embedded IPython terminal for advanced users who want to interact with the optical system programmatically using Optiland's Python API.

Command Palette (Ctrl+K)
~~~~~~~~~~~~~~~~~~~~~~~~

Optiland features a VS Code-style **Command Palette** that provides quick access to various tools, analyses, and layout actions.

*   **Keyboard Shortcut**: Press ``Ctrl+K`` to open the palette.
*   **Functionality**: Type to search for specific commands (e.g., "Open", "Spot Diagram", "Theme"). Use the arrow keys to navigate and ``Enter`` to execute the selected command.

.. note::

   All windows are dockable and can be rearranged to suit your workflow. You can also save your layout for future sessions. These can be loaded by pressing "1" or "2" in the top toolbar, corresponding to the slot used for saving your layout. A saved layout includes the System Viewer tabs shown in separate windows and where those windows are; a layout saved before tabs could be detached docks every tab.

Light theme and Dark theme
--------------------------

The examples above show the default dark theme. If you prefer a light theme, you can easily switch to it under the **View > Theme** menu:

.. image:: _static/gui_switch_theme.png
   :alt: Theme Switch
   :align: center
   :width: 400px

Getting Started: Basic Actions
------------------------------

Let's try a few basic operations.

1. Opening an Existing Lens File
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optiland supports loading and saving its native JSON format (`.json`). Several samples files are included with the installation and can be found in the optiland/docs/samples directory. For this quickstart, we will load the Cooke Triplet lens system:

*   Go to the menu: **File > Open > Cooke_triplet.json**.
*   The Cooke Triplet lens system will load, and you should see its data in the Lens Editor and a 2D/3D representation in the Viewer Panel.

.. note::

   You can also load Optiland files that were saved using the Optiland Python API.

2. Viewing a Raytrace
~~~~~~~~~~~~~~~~~~~~~

With the Cooke Triplet loaded:

*   In the **Viewer Panel**, ensure the **2D View** tab is selected.
*   Experiment with the Matplotlib toolbar controls, such as zooming and panning.
*   Switch to the **3D View** tab in the Viewer Panel to see the lens and rays in 3D. You can rotate, pan, and zoom this view.

3. Changing a Surface Parameter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Let's modify a surface and see the update:

*   In the **Lens Editor Panel**, find the row for **Surface 1** (first surface after object).
*   Double-click on the cell containing its **Radius** value.
*   Change the value (e.g., from 22.0136 to 30.0) and press **Enter**.
*   Observe how the 2D and 3D views in the **Viewer Panel** update to reflect this change. The lens is now defocused.

4. Running an Analysis
~~~~~~~~~~~~~~~~~~~~~~

*   In the **Analysis Panel**, select **RMS Spot Size vs Field** from the list of available analyses. Or, choose another analysis if you prefer.
*   Click the triangular "Run" button to execute the analysis.
*   The results will be displayed in the Analysis Panel, showing a plot of RMS spot size against field angle.

Explore Further
---------------

This quickstart covered only the very basics. The Optiland GUI has many more features for detailed optical design and analysis. We encourage you to explore the menus, right-click options in different panels, and consult the other sections of the Optiland documentation for more in-depth information on specific functionalities.

.. note::

   For the latest and greatest features, the Optiland Python API generally must be used. The GUI does not currently expose all features available in Optiland.
