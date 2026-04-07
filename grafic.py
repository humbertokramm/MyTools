import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
from datetime import datetime


def auto_time_scale(time_array):
    span = np.max(time_array) - np.min(time_array)

    if span >= 1:
        return time_array, "s"
    elif span >= 1e-3:
        return time_array * 1e3, "ms"
    elif span >= 1e-6:
        return time_array * 1e6, "µs"
    else:
        return time_array * 1e9, "ns"


def auto_time_scale(time_array):
    span = np.max(time_array) - np.min(time_array)

    if span >= 1:
        return time_array, "s", 1
    elif span >= 1e-3:
        return time_array * 1e3, "ms", 1e3
    elif span >= 1e-6:
        return time_array * 1e6, "µs", 1e6
    else:
        return time_array * 1e9, "ns", 1e9



def load_csv(filename):
    time = []
    voltage = []
    metadata = {}

    with open(filename + ".csv", newline='') as file:
        lines = file.readlines()

        for line in lines:
            if line.startswith("#"):
                parts = line[1:].strip().split(":", 1)
                if len(parts) == 2:
                    metadata[parts[0].strip()] = parts[1].strip()

        filtered = (
            row for row in lines
            if not row.startswith("#") and row.strip() != ""
        )

        reader = csv.reader(filtered)
        next(reader)

        for row in reader:
            time.append(float(row[0]))
            voltage.append(float(row[1]))

    return np.array(time), np.array(voltage), metadata

def hold(msg= "Press ENTER key to continue...",cont='',abort='q'):
    k = 0
    while(k != cont):
        k = input(msg)
        if k.lower() == abort: exit()

def main(file_list, params=None):

    if isinstance(file_list, str):
        file_list = [file_list]

    if params is None:
        params = {}

    logic_limits = params.get("logic_limits")
    max_limits = params.get("max_limits")
    labels = params.get("labels")
    time_offset = params.get("time_offset")
    colors = params.get("colors")
    show_metadata = params.get("show_metadata", True)
    title = params.get("title", "Waveform")

    fig, ax = plt.subplots(figsize=(10, 5))

    combined_metadata = {}
    waveforms = []
    all_times = []

    # =============================
    # Load all files first
    # =============================
    for file in file_list:
        time, voltage, metadata = load_csv(file)
        waveforms.append((file, time, voltage))
        all_times.append(time)
        combined_metadata.update(metadata)

    # =============================
    # Determine global time scale using your function
    # =============================
    global_time = np.concatenate(all_times)

    _, unit, scale = auto_time_scale(global_time)

    # =============================
    # Plot each waveform with its own time vector
    # =============================
    '''for idx, (file, time, voltage) in enumerate(waveforms):

        time_scaled = time * scale

        label = labels[idx] if labels and idx < len(labels) else file
        color = colors[idx] if colors and idx < len(colors) else None

        ax.plot(time_scaled, voltage, linewidth=1, label=label, color=color'''
        
    
    for idx, (file, time, voltage) in enumerate(waveforms):

        # =============================
        # Apply time offset (seconds)
        # =============================
        offset = time_offset[idx] if time_offset and idx < len(time_offset) else 0
        time_shifted = time - offset
        time_scaled = time_shifted * scale

        label = labels[idx] if labels and idx < len(labels) else file
        color = colors[idx] if colors and idx < len(colors) else None

        ax.plot(time_scaled, voltage, linewidth=1, label=label, color=color)
    
    

    ax.set_xlabel(f"Time ({unit})")
    ax.set_ylabel("Voltage (V)")
    ax.set_title(title)
    ax.grid(True)
    ax.legend()

    formatter = ScalarFormatter(useMathText=True)
    formatter.set_powerlimits((-3, 3))
    ax.yaxis.set_major_formatter(formatter)
    ax.xaxis.set_major_formatter(formatter)

    # =============================
    # Optional logic mask
    # =============================
    if logic_limits:
        ax.axhspan(logic_limits["low_min"], logic_limits["low_max"], alpha=0.15)
        ax.axhspan(logic_limits["high_min"], logic_limits["high_max"], alpha=0.15)

        ax.axhline(logic_limits["low_max"], linestyle='--', linewidth=0.8)
        ax.axhline(logic_limits["high_min"], linestyle='--', linewidth=0.8)

    # Max limits (independent)
    if max_limits:
        ax.axhline(max_limits["low"], linestyle='--', linewidth=0.8, color="red")
        ax.axhline(max_limits["high"], linestyle='--', linewidth=0.8, color="red")

    # =============================
    # Metadata box
    # =============================
    if show_metadata:
        info_text = ""

        if "Instrumento" in combined_metadata:
            model = combined_metadata["Instrumento"].split(",")[1]
            info_text += model + "\n"

        if "Sample Rate (calculado)" in combined_metadata:
            info_text += f"Sample Rate: {combined_metadata['Sample Rate (calculado)']}\n"

        if "Record Length" in combined_metadata:
            info_text += f"Samples: {combined_metadata['Record Length']}\n"

        if "Data da captura" in combined_metadata:
            info_text += f"Capture Date: {combined_metadata['Data da captura']}"

        ax.text(
            0.98, 0.98,
            info_text,
            transform=ax.transAxes,
            fontsize=8,
            verticalalignment='top',
            horizontalalignment='right',
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.6)
        )

    # =============================
    # Save PNG
    # =============================
    png_metadata = {
        "Instrument": combined_metadata.get("Instrumento", ""),
        "Sample Rate": combined_metadata.get("Sample Rate (calculado)", ""),
        "Samples": combined_metadata.get("Record Length", ""),
        "Capture Date": combined_metadata.get("Data da captura", ""),
        "Generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    output_name = title.replace(" ", "_") + ".png"
    plt.savefig(output_name, dpi=300, metadata=png_metadata)

    print(f"PNG saved as: {output_name}")

    plt.show(block=False)
    plt.pause(0.001)