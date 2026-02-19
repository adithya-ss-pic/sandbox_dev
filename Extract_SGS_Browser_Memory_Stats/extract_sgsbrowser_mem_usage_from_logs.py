"""
Python script to extract memory utilization for SGSBrowser from the system log.
Search string: "Total memory usage of sgsbrowser: <value> KiB"

Extracts the timestamp and memory usage value, and plots a graph of time vs memory.

Author: Ss, Adithya (40029958)
Date: 2025-07-20
Version: 1.0.0
"""
import re
import matplotlib.pyplot as plt
from datetime import datetime, timedelta


def parse_log_file(log_file_path):
    """
    Parse the log file and extract timestamps and memory usage data.
    Args:
        log_file_path (str): Path to the log file
    Returns:
        tuple: (timestamps, memory_usages) lists
    """
    # Regular expression to match the log entries
    # Pattern to match: [2025-07-20T14:40:43.292397Z] for date and [16:40:43] for time, plus memory usage
    pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}\.\d+Z\]\[(\d{2}:\d{2}:\d{2})\].*Total memory usage of sgsbrowser: (\d+) KiB')

    timestamps = []
    memory_usages = []

    with open(log_file_path, 'r') as file:
        for line in file:
            match = pattern.search(line)
            if match:
                date_part, time_part, memory_usage_str = match.groups()
                # Combine date and time to create full datetime string
                full_datetime_str = f"{date_part} {time_part}"
                timestamps.append(full_datetime_str)
                memory_usages.append(int(memory_usage_str))
    
    return timestamps, memory_usages


def create_timestamp_memory_mapping(timestamps, memory_usages):
    """
    Create a dictionary mapping timestamps to memory usage values.
    Args:
        timestamps (list): List of timestamp strings
        memory_usages (list): List of memory usage values
    Returns:
        dict: Dictionary mapping timestamps to memory usage
    """
    return dict(zip(timestamps, memory_usages))


def filter_data_by_hours(timestamps, memory_usages, last_hours):
    """
    Filter data to include only the last N hours from the most recent timestamp.
    Args:
        timestamps (list): List of datetime strings in format "YYYY-MM-DD HH:MM:SS"
        memory_usages (list): List of memory usage values
        last_hours (int): Number of hours to include from the latest timestamp
    Returns:
        tuple: (filtered_timestamps, filtered_memory_usages)
    """
    if not timestamps:
        return timestamps, memory_usages
    
    # Convert all timestamps to datetime objects for easier comparison
    time_objects = [(datetime.strptime(t, '%Y-%m-%d %H:%M:%S'), t, memory_usages[i]) 
                    for i, t in enumerate(timestamps)]
    
    # Find the latest timestamp
    latest_time_obj = max(time_objects, key=lambda x: x[0])
    latest_time = latest_time_obj[0]
    
    print(f"Latest timestamp: {latest_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Calculate the cutoff time (last_hours before the latest time)
    cutoff_time = latest_time - timedelta(hours=last_hours)
    
    print(f"Looking for data from {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')} to {latest_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Filter for the time range
    filtered_data = []
    for time_obj, timestamp_str, memory_usage in time_objects:
        if cutoff_time <= time_obj <= latest_time:
            filtered_data.append((timestamp_str, memory_usage))
    
    # Extract filtered lists
    filtered_timestamps = [item[0] for item in filtered_data]
    filtered_memory_usages = [item[1] for item in filtered_data]
    
    return filtered_timestamps, filtered_memory_usages


def print_data_summary(timestamps, memory_usages, timestamp_to_memory, last_hours=None):
    """
    Print summary information about the extracted data.
    Args:
        timestamps (list): List of timestamp strings
        memory_usages (list): List of memory usage values
        timestamp_to_memory (dict): Dictionary mapping timestamps to memory usage
        last_hours (int, optional): Number of hours filtered, if applicable
    """
    if last_hours is not None:
        print(f"Filtered to last {last_hours} hours: {len(timestamps)} entries")
    
    print(f"Extracted Data: {len(timestamps)} entries")
    print(f"Timestamp to Memory mapping created with {len(timestamp_to_memory)} entries")
    print(timestamp_to_memory)


def plot_memory_usage(timestamps, memory_usages):
    """
    Create and display a plot of memory usage over time.
    Args:
        timestamps (list): List of datetime strings in format "YYYY-MM-DD HH:MM:SS"
        memory_usages (list): List of memory usage values
    """
    # Plotting the results
    plt.figure(figsize=(12, 6))
    # Convert datetime strings to datetime objects for plotting
    time_objects = [datetime.strptime(t, '%Y-%m-%d %H:%M:%S') for t in timestamps]
    plt.plot(time_objects, memory_usages, marker='o')
    plt.title('SGSBrowser Memory Usage Over Time')
    plt.xlabel('Date and Time')
    plt.ylabel('Memory Usage (KiB)')
    
    # Set x-axis ticks to show every 1 hour
    from matplotlib.dates import DateFormatter, HourLocator, MinuteLocator
    
    # Use HourLocator for better hour-based ticking
    plt.gca().xaxis.set_major_locator(HourLocator(interval=1))
    plt.gca().xaxis.set_major_formatter(DateFormatter('%m-%d %H:%M'))
    
    # Add minor ticks every 30 minutes for better granularity
    plt.gca().xaxis.set_minor_locator(MinuteLocator(byminute=[0, 30]))
    
    # Force the x-axis to show the full range with hourly ticks
    if time_objects:
        start_time = min(time_objects)
        end_time = max(time_objects)
        
        # Expand the range to show at least one hour before and after if data spans less
        time_range = end_time - start_time
        if time_range.total_seconds() < 3600:  # Less than 1 hour
            # Extend range to show at least 2 hours
            start_time = start_time - timedelta(minutes=30)
            end_time = end_time + timedelta(minutes=30)
        
        plt.xlim(start_time, end_time)
    
    plt.xticks(rotation=45)
    plt.grid(True, which='major', alpha=0.7)
    plt.grid(True, which='minor', alpha=0.3)
    plt.tight_layout()
    plt.show()


def extract_sgsbrowser_mem_usage_from_logs(log_file_path, last_hours=None):
    """
    Main function to extract and analyze SGSBrowser memory usage from logs.
    Args:
        log_file_path (str): Path to the log file
        last_hours (int, optional): Number of hours to include from the latest timestamp
    Returns:
        dict: Dictionary mapping timestamps to memory usage values
    """
    # Parse the log file
    timestamps, memory_usages = parse_log_file(log_file_path)
    
    # Filter data if last_hours is specified
    if last_hours is not None:
        timestamps, memory_usages = filter_data_by_hours(timestamps, memory_usages, last_hours)
    
    # Create timestamp to memory mapping
    timestamp_to_memory = create_timestamp_memory_mapping(timestamps, memory_usages)
    
    # Print data summary
    print_data_summary(timestamps, memory_usages, timestamp_to_memory, last_hours)
    
    # Plot the data
    if timestamps:  # Only plot if we have data
        plot_memory_usage(timestamps, memory_usages)
    else:
        print("No data to plot.")
    
    return timestamp_to_memory

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python extract_sgsbrowser_mem_usage_from_logs.py <log_file_path> [last_hours]")
        print("  log_file_path: Path to the log file")
        print("  last_hours: Optional - Number of hours from the latest timestamp to plot (e.g., 12)")
        sys.exit(1)

    log_file_path = sys.argv[1]
    last_hours = None
    
    if len(sys.argv) == 3:
        try:
            last_hours = int(sys.argv[2])
            if last_hours <= 0:
                print("Error: last_hours must be a positive integer")
                sys.exit(1)
        except ValueError:
            print("Error: last_hours must be a valid integer")
            sys.exit(1)
    
    extract_sgsbrowser_mem_usage_from_logs(log_file_path, last_hours)