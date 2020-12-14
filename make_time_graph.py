import argparse
import csv
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

INPUT_DIR = "results/run_0"
MAX = 30
TO_NANOSECONDS = 1e9

def make_graph(input_dir, title):
    data = []
    valid_data = 0
    total_data = 0
    dividers = np.linspace(0, MAX, MAX + 1).tolist()
    for idx, div in enumerate(dividers):
        dividers[idx] = round(div, 1)

    divider_to_index = {}
    for idx, div in enumerate(dividers):
        divider_to_index[idx] = idx

    files = os.listdir(input_dir)
    files_to_get = []
    for f in files:
        if "stats" in f:
            files_to_get.append(f)

    for f in files_to_get:
        with open(input_dir+'/'+f) as file:
            reader = csv.reader(file)
            for row in reader:
                if "lat_avg" not in row[-1]:
                    total_data += 1
                    if "...." not in row[-1]:  # this is a valid latency
                        valid_data += 1
                        data.append(float(row[-2]))  # only add latency in seconds
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
        palette='muted',
        legend=False,
        bins=MAX
    )
    ax.set(xlabel="Latency", ylabel="Number of Runs")
    ax.set_xticks(dividers)
    ax.set_facecolor('xkcd:light grey')

    plt.savefig('time.png')
    plt.show()


def main(args):
    make_graph(args.input_dir, "title")

    #preprocess_data(args.input_dir, args.prom_file)
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Make a graph from data.')
    parser.add_argument("-i", "--input_dir", dest="input_dir",
                        default=INPUT_DIR,
                        help="File of data to make a graph of. ")
    parser.add_argument("-p", "--prom_file", dest="prom_file",
                        default="prom.csv",
                        help="File of prometheus data to make a graph of. ")
    parser.add_argument("-t", "--graph_title", dest="graph_title",
                        default="Latency Markers",
                        help="The title of the graph. ")

    arguments = parser.parse_args()
    main(arguments)
