# CoreVanguard Telemetry Suite 

**CoreVanguard** is a lightweight, low-latency hardware monitoring overlay designed for PC gamers and power users. Built entirely in Python, it directly hooks into kernel-level data to provide real-time thermal throttling alerts, frame timing, and system resource management without the heavy overhead of traditional monitoring software.

<img width="959" height="540" alt="Screenshot 2026-08-06 094618" src="https://github.com/user-attachments/assets/d10732ab-54dc-4764-a025-fc0b41ccf125" />


## Key Features

*   **Kernel-Level Frame Timing (ETW):** Utilizes a background subprocess to read Intel PresentMon's Event Tracing for Windows (ETW) pipeline. This captures highly accurate application framerates (FPS) and frame-times without injecting code into the game process, ensuring 100% safety from Anti-Cheat bans.
*   **Hybrid Thermal Tripwires:** Features a recursive search algorithm that parses live JSON telemetry from LibreHardwareMonitor. It actively hunts for silicon-level thermal limit flags (e.g., "Package Thermal Throttling") and triggers a custom pulsing UI alarm before catastrophic system degradation occurs.
*   **Standby RAM Purger:** Integrates direct Windows Native API calls (`ctypes.windll.ntdll`) to instantly flush the OS standby memory cache, mitigating micro-stutters in memory-intensive applications.
*   **Dynamic Vector UI:** A fully responsive CustomTkinter dashboard utilizing mathematically drawn `Canvas` vector gauges. The UI is tied to a master state engine that seamlessly synchronizes colors and text contrast across all widgets when a new theme is selected.
*   **Game-Style Keybinder:** A dynamic hotkey listener that allows users to instantly bind custom multi-key combinations (e.g., `Shift+H`) to toggle the borderless in-game OSD (On-Screen Display).

## System Architecture

This project was engineered with a strict adherence to **Object-Oriented Programming (OOP)** principles to manage the complexity of asynchronous data feeds and graphical rendering:

*   **Inheritance:** The in-game overlay (`HUDOverlay`) inherits directly from `tkinter.Toplevel`, specializing a standard OS window manager into a borderless, transparent, topmost widget.
*   **Composition:** The central `CoreVanguardEngine` acts as the master controller, owning independent instances of `PresentMonReader`, `CPUSensor`, and `VectorGauge` objects.
*   **Encapsulation:** Network requests and JSON parsing are encapsulated within the sensor classes. The main UI thread interacts with these classes through clean `.fetch_data()` methods, completely isolating network logic from the visual rendering pipeline.
*   **Multithreading:** Data acquisition (polling hardware temperatures and reading the ETW pipeline) is isolated onto Python **Daemon Threads**, ensuring the main GUI loop remains unblocked and perfectly fluid at all times.

## Installation & Usage

CoreVanguard is packaged as a portable executable and requires no installation.

1. Download the latest release `.zip` from the **Releases** tab.
2. Extract the folder to your desired location.
3. Open the `LibreHardwareMonitor` folder and run `LibreHardwareMonitor.exe`.
4. In LibreHardwareMonitor, navigate to **Options -> Remote Web Server -> Run**. (You can minimize this to the system tray).
5. Run `CoreVanguard.exe` as an Administrator (required for the RAM purger and ETW hooks).

## Developer
Developed and architected by **Mahir Azman Murad**
*Computer Engineering, Ghulam Ishaq Khan Institute of Engineering Sciences and Technology (GIKI)*
