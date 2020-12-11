#!/usr/bin/env python3
import argparse
import csv
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.dates as md
import util

log = logging.getLogger(__name__)


FILE_DIR = Path(__file__).parent.resolve()
RESULT_DIR = FILE_DIR.joinpath("results")
INPUT_FOLDER = RESULT_DIR.joinpath("run_0")
MAX = 5


def make_graph_old(input_file, title):
    data = []
    valid_data = 0
    total_data = 0
    dividers = np.linspace(0, MAX, MAX * 10 + 1).tolist()
    for idx, div in enumerate(dividers):
        dividers[idx] = round(div, 1)

    divider_to_index = {}
    for idx, div in enumerate(dividers):
        divider_to_index[idx] = idx

    with open(input_file) as file:
        reader = csv.reader(file)
        for row in reader:
            row = row[-1].split()
            if "seconds" not in row[-1]:
                total_data += 1
                if "...." not in row[-1]:  # this is a valid latency
                    valid_data += 1
                    data.append(float(row[-1]))  # only add latency in seconds
    data = pd.DataFrame(data)
    binned_data = pd.cut(data[0], bins=dividers)

    data_to_graph = []
    for datapoint in binned_data:
        data_to_graph.append(datapoint.left)
    data_to_graph = pd.DataFrame(data_to_graph)
    f, ax = plt.subplots(figsize=(7, 5))
    sns.despine(f)

    sns.histplot(
        data_to_graph,
        palette="muted",
        legend=False
    )
    ax.set(xlabel="Latency", ylabel="Number of Runs")
    ax.set_xticks(np.linspace(0, MAX, MAX).tolist())
    ax.set_facecolor("xkcd:light grey")
    ax.set_title(title)
    plt.savefig("test.png")
    plt.show()


def create_prom_data(input_folder, use_error_bars=False):
    prom_files = input_folder.glob("prom_*.csv")
    prom_dfs = []
    for prom_f in prom_files:
        df = pd.read_csv(prom_f, index_col=0)
        prom_dfs.append(df)

    if not prom_dfs:
        log.error("No input data! Exiting...")
        exit(util.EXIT_FAILURE)
    if use_error_bars:
        prom_frame = pd.concat(prom_dfs, axis=1).fillna(method='ffill')
        prom_frame = prom_frame.melt(ignore_index=False, value_name="Lat")
        prom_frame = prom_frame.drop("variable", 1)
    else:
        prom_frame = prom_dfs[0]
        if len(prom_dfs) > 1:
            for merge_prom_frame in prom_dfs[1:]:
                prom_frame = pd.merge_asof(prom_frame, merge_prom_frame,
                                           on="Time", direction="nearest")
            prom_frame = prom_frame.set_index("Time")
        prom_frame = prom_frame.mean(axis=1).to_frame()
    # some manual adjustments needed
    prom_frame.columns = ["Latency"]
    prom_frame.index = pd.to_datetime(prom_frame.index.astype(int), unit="ns")
    log.info(prom_frame)
    return prom_frame


def create_stats_data(input_folder):
    stats_files = input_folder.glob("stats_*.csv")
    stats_dfs = []
    for stats_f in stats_files:
        stats_dfs.append(pd.read_csv(stats_f))
    stats_frame = pd.concat(stats_dfs)
    stats_frame.reset_index(drop=True, inplace=True)
    stats_frame = stats_frame[stats_frame["is_congested"] == "yes"].mean()
    return stats_frame


def make_graph(input_folder, use_error_bars):
    # Set seaborn style for plotting
    sns.set(style="whitegrid", rc={"lines.linewidth": 2.0,
                                   "axes.spines.right": False,
                                   "axes.spines.top": False,
                                   'lines.markeredgewidth': 0.1})
    prom_frame = create_prom_data(input_folder, use_error_bars)
    stats_frame = create_stats_data(input_folder)
    c_start = stats_frame["congestion_start"].astype("datetime64[ns]")
    c_dect = stats_frame["congestion_detected"].astype("datetime64[ns]")
    c_cleared = stats_frame["congestion_cleared"].astype("datetime64[ns]")
    fig, ax = plt.subplots(figsize=(10, 4), squeeze=True)
    ax.set_ylabel("90th percentile request latency (ms)")
    ax.set_xlabel("Time (mm:ss)")
    plt.xticks(rotation=15)
    ax.margins(y=0.05)
    ax.axvline(x=c_start, color="red", linestyle="--",
               label="Congestion inserted")
    ax.axvline(x=c_dect, color="orange", linestyle="--",
               label="Congestion detected")
    ax.axvline(x=c_cleared, color="green", linestyle="--",
               label="Congestion removed")
    ax.legend(bbox_to_anchor=(0.5, 1.15), loc="upper center",
              fancybox=True, shadow=True, ncol=3)
    ax.xaxis.set_major_formatter(md.DateFormatter("%M:%S"))
    sns.lineplot(ax=ax, x="Time", y="Latency", data=prom_frame, legend=False)
    plt.savefig("test.png", bbox_inches='tight', pad_inches=0.10)
    plt.gcf().clear()


def main(args):
    input_folder = Path(args.input_folder)
    make_graph(input_folder, args.use_error_bars)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Make a graph from data.")
    parser.add_argument("-l", "--log-file", dest="log_file",
                        default="graph.log",
                        help="Specifies name of the log file.")
    parser.add_argument("-ll", "--log-level", dest="log_level",
                        default="INFO",
                        choices=["CRITICAL", "ERROR", "WARNING",
                                 "INFO", "DEBUG", "NOTSET"],
                        help="The log level to choose.")
    parser.add_argument("-i", "--input_folder", dest="input_folder",
                        default=INPUT_FOLDER,
                        help="File of data to make a graph of. ")
    parser.add_argument("-t", "--graph_title", dest="graph_title",
                        default="Latency Markers",
                        help="The title of the graph. ")
    parser.add_argument("-e", "--error-bars", dest="use_error_bars",
                        action="store_true",
                        help="Plot with error bars")
    # Parse options and process argv
    arguments = parser.parse_args()
    # configure logging
    logging.basicConfig(filename=arguments.log_file,
                        format="%(levelname)s:%(message)s",
                        level=getattr(logging, arguments.log_level),
                        filemode="w")
    stderr_log = logging.StreamHandler()
    stderr_log.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logging.getLogger().addHandler(stderr_log)
    main(arguments)
