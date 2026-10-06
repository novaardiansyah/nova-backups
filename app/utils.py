def format_size(size_bytes: int | float) -> str:
    if size_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    val = float(size_bytes)
    while val >= 1024 and unit_index < len(units) - 1:
        val /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(val)} B"
    formatted = f"{val:.2f}"
    if formatted.endswith(".00"):
        return f"{int(val)} {units[unit_index]}"
    if formatted.endswith("0"):
        return f"{val:.1f} {units[unit_index]}"
    return f"{formatted} {units[unit_index]}"


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec <= 0:
        return "0 B/s"
    return f"{format_size(bytes_per_sec)}/s"
