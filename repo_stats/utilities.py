import numpy as np
import ast
from datetime import datetime, timezone


def rolling_average(unaveraged, window):
    """
    Obtain a rolling average of 'unaveraged' data in a sliding window of index length 'window'

    Arguments
    ---------
    unaveraged : list
        Data to be averaged
    window : int
        Width (in indices) of sliding window. Enforced to be odd

    Returns
    -------
    roll_avg : array
        Averaged data
    window : int
        The input 'window', potentially decreased by 1 to make odd
    """
    if not window % 2:
        print("window_avg should be odd --> decreasing by 1")
        window -= 1

    roll_avg = np.convolve(unaveraged, np.ones(window), mode="valid") / window

    return roll_avg, window


def fill_missed_months(unique_output):
    """
    For an output of 'np.unique(x, return_counts=True)' where 'x' is a list of dates of the format '2024-01', fill in months missing in this list and set their count to 0.

    Arguments
    ---------
    unique_output : tuple of array
        Output of 'np.unique'

    Returns
    -------
    unique_output : list of array
        The input updated with inserted entries for missing months
    """
    unique_output = list(unique_output)

    now = datetime.now(timezone.utc)

    # build list of 'year-month' from oldest entry in 'unique_output' to current month
    oldest, newest = min(unique_output[0]), f"{now.year}-{now.month:02d}"
    years = [str(y) for y in list(range(int(oldest[:4]), int(newest[:4]) + 1))]
    months = [f"{m:02d}" for m in list(range(1, 13))]
    dates = []
    for y in years:
        for m in months:
            dates.append(f"{y}-{m}")
    dates = dates[dates.index(oldest) : dates.index(newest) + 1]

    # insert missing dates into 'unique_output'
    missed_months = [i for i in dates if i not in unique_output[0]]
    for i in missed_months:
        idx = np.searchsorted(unique_output[0], i)
        unique_output[0] = np.insert(unique_output[0], idx, i)
        unique_output[1] = np.insert(unique_output[1], idx, 0)

    return unique_output


