############################################################
#
# analyze_pairings.py
#
# Exploratory analysis of pairings <W,W^T>
# for 4x4 standard Young tableaux.
#
############################################################

import ast
import os
import sys
import math
import itertools
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

############################################################
# Optional machine learning imports.
#
# The program still runs if sklearn is unavailable,
# but ML analyses will be skipped.
############################################################

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.inspection import permutation_importance

    SKLEARN_AVAILABLE = True

except ImportError:

    SKLEARN_AVAILABLE = False


############################################################
# Read pairing file
############################################################

def read_pairing_file(filename):
    """
    Reads a file consisting of triples

        (W, X, pairing)

    Returns

        list of dictionaries

    where each dictionary has keys

        word
        transpose
        sign
    """

    data = []

    with open(filename) as f:

        for lineno, line in enumerate(f, start=1):

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            try:
                W, X, value = ast.literal_eval(line)

            except Exception:

                print(f"Could not parse line {lineno}")
                print(line)
                raise

            if value not in (-1, 1):
                raise ValueError(
                    f"Unexpected pairing value {value} on line {lineno}"
                )

            data.append({

                "word": str(W),
                "transpose": str(X),
                "sign": int(value)

            })

    return data


############################################################
# Basic consistency checks
############################################################

def sanity_checks(data):

    print()

    print("=" * 60)
    print("DATA SUMMARY")
    print("=" * 60)

    print("Number of examples:", len(data))

    lengths = Counter(len(x["word"]) for x in data)

    print("Word lengths:", dict(lengths))

    signs = Counter(x["sign"] for x in data)

    print("Signs:", dict(signs))

    ########################################################

    duplicates = len(data) - len(set(x["word"] for x in data))

    print("Duplicate W words:", duplicates)

    ########################################################

    bad = []

    for x in data:

        w = x["word"]

        counts = Counter(w)

        if counts != Counter({

            "1":4,
            "2":4,
            "3":4,
            "4":4

        }):

            bad.append(w)

    print("Words with incorrect multiplicities:", len(bad))

    ########################################################

    if bad:

        print()
        print("Examples:")
        for w in bad[:10]:
            print(w)

    print()


############################################################
# Yamanouchi words and tableaux
############################################################

def is_yamanouchi(word):
    """
    Checks whether a word is Yamanouchi (lattice).

    Reading from right to left,
    every suffix contains

        #1 >= #2 >= #3 >= #4.
    """

    c = [0,0,0,0]

    for ch in reversed(word):

        c[int(ch)-1] += 1

        if not (c[0] >= c[1] >= c[2] >= c[3]):
            return False

    return True


def word_to_tableau(word):
    """
    Converts a Yamanouchi word into a 4x4 tableau.

    The i-th occurrence of digit r is placed
    into row r.

    Returns

        rows = [
            [ ... ],
            [ ... ],
            [ ... ],
            [ ... ]
        ]
    """

    rows = [[],[],[],[]]

    for number, digit in enumerate(word, start=1):

        rows[int(digit)-1].append(number)

    return rows


def transpose_tableau(rows):

    return [list(col) for col in zip(*rows)]


def print_tableau(rows):

    for r in rows:
        print(" ".join(f"{x:2d}" for x in r))


############################################################
# Basic tableau statistics
############################################################

def descent_set(rows):
    """
    Descent set of a standard tableau.

    i is a descent if i+1 lies in a lower row.
    """

    position = {}

    for r,row in enumerate(rows):
        for x in row:
            position[x] = r

    D = []

    for i in range(1,16):

        if position[i+1] > position[i]:
            D.append(i)

    return D


def major_index(rows):

    return sum(descent_set(rows))


def row_of_entries(rows):

    pos = {}

    for r,row in enumerate(rows):
        for x in row:
            pos[x] = r

    return pos


############################################################
# Word statistics
############################################################

def inversion_number(word):

    inv = 0

    n = len(word)

    for i in range(n):

        for j in range(i+1,n):

            if word[i] > word[j]:
                inv += 1

    return inv


def first_occurrences(word):

    return {
        d: word.index(str(d))
        for d in range(1,5)
    }


def last_occurrences(word):

    return {
        d: word.rindex(str(d))
        for d in range(1,5)
    }


def transition_counts(word):
    """
    Count adjacent pairs:

        11
        12
        ...
        44

    """

    C = Counter()

    for a,b in zip(word[:-1],word[1:]):

        C[a+b] += 1

    return C


############################################################
# Feature extraction
############################################################

def compute_features(example):

    word = example["word"]

    rows = word_to_tableau(word)

    desc = descent_set(rows)

    inv = inversion_number(word)

    first = first_occurrences(word)

    last = last_occurrences(word)

    trans = transition_counts(word)

    F = {}

    ########################################################
    # scalar statistics
    ########################################################

    F["inv"] = inv
    F["inv_parity"] = inv % 2

    F["num_descents"] = len(desc)
    F["major_index"] = sum(desc)

    ########################################################
    # first/last positions
    ########################################################

    for d in range(1,5):

        F[f"first_{d}"] = first[d]
        F[f"last_{d}"] = last[d]

    ########################################################
    # transition counts
    ########################################################

    for a in "1234":
        for b in "1234":

            F[f"pair_{a}{b}"] = trans[a+b]

    ########################################################
    # row endpoints
    ########################################################

    for r in range(4):

        F[f"row{r+1}_max"] = max(rows[r])
        F[f"row{r+1}_min"] = min(rows[r])

        ########################################################
    # Run statistics
    ########################################################

    runs = run_lengths(word)

    F["num_runs"] = len(runs)
    F["max_run"] = max(runs)
    F["mean_run"] = sum(runs)/len(runs)

    ########################################################
    # Transition profile
    ########################################################

    profile = row_transition_profile(word)

    for key in ["same","plus1","plus2","plus3","down"]:

        F["transition_"+key] = profile[key]

    ########################################################
    # Every contiguous pattern of length 2
    ########################################################

    P2 = pattern_counts(word,2)

    for pattern,count in P2.items():

        F["pat2_"+pattern] = count

    ########################################################
    # Every contiguous pattern of length 3
    ########################################################

    P3 = pattern_counts(word,3)

    for pattern,count in P3.items():

        F["pat3_"+pattern] = count

    ########################################################
    # Prefix statistics
    ########################################################

    for k in range(1,16):

        prefix = word[:k]

        F[f"prefix1_{k}"] = prefix.count("1")
        F[f"prefix2_{k}"] = prefix.count("2")
        F[f"prefix3_{k}"] = prefix.count("3")
        F[f"prefix4_{k}"] = prefix.count("4")
    
    return F

############################################################
# Additional feature extraction
############################################################

def pattern_counts(word, length):
    """
    Count every contiguous pattern of a given length.

    Example:

        length = 2

        112233

    produces counts of

        11
        12
        22
        23
        33

    """

    C = Counter()

    for i in range(len(word)-length+1):
        C[word[i:i+length]] += 1

    return C


def run_lengths(word):
    """
    Lengths of maximal runs.

    Example

        111223311

    gives

        [3,2,2,2]
    """

    runs = []

    current = 1

    for a,b in zip(word[:-1],word[1:]):

        if a==b:
            current += 1
        else:
            runs.append(current)
            current = 1

    runs.append(current)

    return runs


def row_transition_profile(word):
    """
    How often does the word

        stay in same row,
        increase by one,
        increase by two,
        increase by three,
        decrease.

    """

    result = Counter()

    nums = [int(c) for c in word]

    for a,b in zip(nums[:-1],nums[1:]):

        d = b-a

        if d==0:
            result["same"] += 1
        elif d>0:
            result[f"plus{d}"] += 1
        else:
            result["down"] += 1

    return result


############################################################
# Extend compute_features
############################################################
############################################################
# Convert to dataframe
############################################################

def build_dataframe(data):

    rows = []

    for example in data:

        F = compute_features(example)

        F["word"] = example["word"]
        F["sign"] = example["sign"]

        rows.append(F)

    df = pd.DataFrame(rows)

    df = df.fillna(0)

    return df


############################################################
# Machine learning
############################################################

def run_machine_learning(df):

    if not SKLEARN_AVAILABLE:
        print("scikit-learn not installed.")
        return

    print()
    print("="*60)
    print("MACHINE LEARNING")
    print("="*60)

    ########################################################
    # Build X,y
    ########################################################

    feature_columns = [
        c for c in df.columns
        if c not in ("word", "sign")
    ]

    X = df[feature_columns]
    y = (df["sign"] == 1).astype(int)

    ########################################################
    # Decision tree
    ########################################################

    tree = DecisionTreeClassifier(
        max_depth=4,
        random_state=0
    )

    tree.fit(X, y)

    tree_score = cross_val_score(
        tree,
        X,
        y,
        cv=5
    )

    print()
    print("Decision tree accuracy:")
    print(
        tree_score.mean(),
        "+/-",
        tree_score.std()
    )

    ########################################################
    # Random forest
    ########################################################

    forest = RandomForestClassifier(

        n_estimators=500,

        random_state=0

    )

    forest.fit(X, y)

    forest_score = cross_val_score(

        forest,

        X,

        y,

        cv=5

    )

    print()

    print("Random forest accuracy:")

    print(

        forest_score.mean(),

        "+/-",

        forest_score.std()

    )

    ########################################################
    # Logistic regression
    ########################################################

    logistic = LogisticRegression(

        max_iter=5000

    )

    logistic.fit(X, y)

    logistic_score = cross_val_score(

        logistic,

        X,

        y,

        cv=5

    )

    print()

    print("Logistic regression accuracy:")

    print(

        logistic_score.mean(),

        "+/-",

        logistic_score.std()

    )
    
        ########################################################
    # Random forest importance
    ########################################################

    importance = pd.Series(

        forest.feature_importances_,

        index=feature_columns

    )

    importance = importance.sort_values(

        ascending=False

    )

    print()

    print("="*60)

    print("Top 20 Random Forest Features")

    print("="*60)

    print()

    print(importance.head(20))

    importance.head(50).to_csv(

        "feature_importance.csv",

        header=["importance"]

    )
    
        ########################################################
    # Logistic coefficients
    ########################################################

    coef = pd.Series(

        logistic.coef_[0],

        index=feature_columns

    )

    coef = coef.reindex(

        coef.abs().sort_values(

            ascending=False

        ).index

    )

    print()

    print("="*60)

    print("Largest Logistic Coefficients")

    print("="*60)

    print()

    print(coef.head(20))

    coef.to_csv(

        "logistic_coefficients.csv",

        header=["coefficient"]

    )
    
        ########################################################
    # Best single feature
    ########################################################

    print()

    print("="*60)

    print("Best Individual Features")

    print("="*60)

    print()

    scores = []

    for feature in feature_columns:

        Xi = X[[feature]]

        model = LogisticRegression(

            max_iter=5000

        )

        s = cross_val_score(

            model,

            Xi,

            y,

            cv=5

        ).mean()

        scores.append(

            (s, feature)

        )

    scores.sort(reverse=True)

    for score, feature in scores[:20]:

        print(

            f"{feature:25s}",

            f"{score:.3f}"

        )


############################################################
# Rule search
############################################################

def parity(x):
    return x % 2


def search_single_feature_rules(df):

    print()
    print("="*60)
    print("SINGLE FEATURE PARITY SEARCH")
    print("="*60)

    feature_columns = [
        c for c in df.columns
        if c not in ("word","sign")
    ]

    truth = (df["sign"] == 1)

    rules = []

    for feature in feature_columns:

        even_prediction = (
            df[feature] % 2 == 0
        )

        odd_prediction = (
            df[feature] % 2 == 1
        )

        even_acc = (even_prediction == truth).mean()

        odd_acc = (odd_prediction == truth).mean()

        rules.append(
            (
                max(even_acc,odd_acc),
                feature,
                even_acc,
                odd_acc
            )
        )

    rules.sort(reverse=True)

    for acc,feature,even,odd in rules[:20]:

        print(
            f"{feature:25s}"
            f"{acc:.3f}"
        )

    return rules
        
def search_two_feature_rules(df):

    print()
    print("="*60)
    print("PAIRWISE PARITY SEARCH")
    print("="*60)

    feature_columns = [
        c for c in df.columns
        if c not in ("word","sign")
    ]

    truth = (df["sign"] == 1)

    best = []

    for i,f1 in enumerate(feature_columns):

        for f2 in feature_columns[i+1:]:

            prediction = (
                (df[f1]+df[f2]) % 2 == 0
            )

            acc = (
                prediction == truth
            ).mean()

            best.append(
                (
                    acc,
                    f1,
                    f2
                )
            )

    best.sort(reverse=True)

    for acc,f1,f2 in best[:20]:

        print(
            f"{f1:20s}"
            f"{f2:20s}"
            f"{acc:.3f}"
        )

    return best

############################################################
# Main
############################################################

def main():

    if len(sys.argv) != 2:

        print()
        print("Usage:")
        print()
        print("python analyze_pairings.py data.txt")
        print()

        return

    filename = sys.argv[1]

    if not os.path.exists(filename):

        print("Cannot find", filename)
        return

    data = read_pairing_file(filename)

    sanity_checks(data)
    
    print("Checking Yamanouchi property...")

    bad = sum(not is_yamanouchi(x["word"]) for x in data)

    print("Non-Yamanouchi words:", bad)

    print()

    print("Example tableau:\n")

    T = word_to_tableau(data[0]["word"])

    print_tableau(T)

    print()

    ############################################################

    df = build_dataframe(data)

    print()

    print("Number of examples:", len(df))
    print("Number of features:", len(df.columns)-2)

    print()

    print("Saving features.csv")

    df.to_csv("features.csv", index=False)

    print()

    print(df.head())

    run_machine_learning(df)

    search_single_feature_rules(df)

    search_two_feature_rules(df)
    
if __name__ == "__main__":

    main()