import argparse
import csv
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

INPUT_FILE = "input_file.csv"
MAX = 5


def make_graph(input_file, title):
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
        palette='muted',
        legend=False
    )
    ax.set(xlabel="Latency", ylabel="Number of Runs")
    ax.set_xticks(np.linspace(0, MAX, MAX).tolist())
    ax.set_facecolor('xkcd:light grey')
    ax.set_title(title)
    plt.savefig('test.png')
    plt.show()


def main(args):
    make_graph(args.input_file, args.graph_title)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Make a graph from data.')
    parser.add_argument("-i", "--input_file", dest="input_file",
                        default=INPUT_FILE,
                        help="File of data to make a graph of. ")
    parser.add_argument("-t", "--graph_title", dest="graph_title",
                        default="Latency Markers",
                        help="The title of the graph. ")

    arguments = parser.parse_args()
    main(arguments)
