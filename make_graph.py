#!/usr/bin/env python3
import sys
import argparse
import logging
from pathlib import Path
import matplotlib.ticker as ticker
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.dates as md
import util

log = logging.getLogger(__name__)


FILE_DIR = Path(__file__).parent.resolve()
RESULT_DIR = FILE_DIR.joinpath("results")
PLOT_DIR = FILE_DIR.joinpath("plots")
INPUT_FOLDER = RESULT_DIR.joinpath("run_0")


def create_prom_data(input_folder, use_error_bars=False):
    prom_files = input_folder.glob("prom_*.csv")
    prom_dfs = []
    for prom_f in prom_files:
        df = pd.read_csv(prom_f, index_col=0)
        prom_dfs.append(df)

    if not prom_dfs:
        log.error("No input data! Exiting...")
        sys.exit(util.EXIT_FAILURE)
    if use_error_bars:
        prom_frame = pd.concat(prom_dfs, axis=1).fillna(method="ffill")
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


def make_line_graph(input_folder, use_error_bars):
    prom_frame = create_prom_data(input_folder, use_error_bars)
    stats_frame = create_stats_data(input_folder)
    c_start = stats_frame["congestion_start"].astype("datetime64[ns]")
    c_dect = stats_frame["congestion_detected"].astype("datetime64[ns]")
    c_cleared = stats_frame["congestion_cleared"].astype("datetime64[ns]")
    _, ax = plt.subplots(figsize=(10, 4), squeeze=True)
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
    output_graph = PLOT_DIR.joinpath("line_graph")
    plt.savefig(output_graph.with_suffix(".png"),
                bbox_inches="tight", pad_inches=0.10)
    plt.savefig(output_graph.with_suffix(".pdf"),
                bbox_inches="tight", pad_inches=0.10)
    plt.gcf().clear()


def make_bar_graph(input_folder):
    stats_files = input_folder.glob("stats_*.csv")
    stats_dfs = []
    for stats_f in stats_files:
        stats_dfs.append(pd.read_csv(stats_f))
    stats_frame = pd.concat(stats_dfs)
    stats_frame.reset_index(drop=True, inplace=True)
    _, ax = plt.subplots(figsize=(10, 4), squeeze=True)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
    ax.set_xlabel("Time to detect in seconds")
    sns.histplot(ax=ax, data=stats_frame, x="delta_s",
                 kde="true", binwidth=1, kde_kws={"bw_adjust": 1})
    output_graph = PLOT_DIR.joinpath("bar_graph")
    plt.savefig(output_graph.with_suffix(".png"),
                bbox_inches="tight", pad_inches=0.10)
    plt.savefig(output_graph.with_suffix(".pdf"),
                bbox_inches="tight", pad_inches=0.10)
    plt.gcf().clear()


def main(args):
    util.check_dir(PLOT_DIR)
    input_folder = Path(args.input_folder)
    # Set consistent seaborn style for plotting
    sns.set(style="white", rc={"lines.linewidth": 2.0,
                               "axes.spines.right": False,
                               "axes.spines.top": False,
                               "lines.markeredgewidth": 0.1})
    make_line_graph(input_folder, args.use_error_bars)
    make_bar_graph(input_folder)


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
