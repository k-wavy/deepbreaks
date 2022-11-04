import re
import numpy as np
import pandas as pd
from itertools import combinations
from scipy.stats import chi2_contingency
from scipy.stats import mode
from scipy.stats import kruskal
from scipy.spatial.distance import pdist
from scipy.spatial.distance import squareform
import csv


# sample size and classes check
def check_data(meta_data, feature, model_type):
    if len(meta_data) < 30:
        raise Exception('Minimum sample size for a regression analysis is 30 samples, '
                        'you provided {} samples!'.format(len(meta_dat)))
    elif model_type == 'cl':
        vl = meta_data[feature].value_counts() / meta_data.shape[0]
        if len(vl) == 1:
            raise Exception(
                'Minimum categories for a classification analysis is 2 classes, you provided {}'.format(len(vl)))
        elif vl[1] < 1/(len(vl)*2):
            raise Exception('Provided sample is highly im-balanced, we need more data for the minority group.')
        else:
            message = "let's start the analysis"
    else:
        message = "let's start the analysis"

    return print(message)


# read fasta file
def fasta_read(f_name):
    f = open(f_name, 'r')
    lines = f.readlines()
    id_re = re.compile(r'>(\S+)')
    seq_re = re.compile(r'^(\S+)$')

    tmp = {}

    for line in lines:
        id_h = id_re.search(line)
        if id_h:
            seq_l = None
            id = id_h.group(1)
        else:
            if seq_l is None:
                seq_l = seq_re.search(line).group(1)
            else:
                seq_l = seq_l+seq_re.search(line).group(1)
            tmp[id] = list(seq_l.upper())
    return pd.DataFrame.from_dict(tmp, orient='index')


# read data function
def read_data(file_path, seq_type=None, is_main=True):
    #
    if file_path.endswith('.csv'):
        dat = pd.read_csv(file_path, sep=',', index_col=0)
    elif file_path.endswith('.tsv'):
        dat = pd.read_csv(file_path, sep='\t', index_col=0)
    elif file_path.endswith(('.xlsx', '.xls')):
        dat = pd.read_excel(file_path, sep='\t', index_col=0)
    elif file_path.endswith('.fasta'):
        # importing seq data
        dat = fasta_read(f_name=file_path)
    else:
        print('For now, we can only read csv, tsv, excel, and fasta files.')
        exit()

    if is_main:
        # naming each position as p + its rank
        dat.columns = [str('p' + str(i)) for i in range(1, dat.shape[1] + 1)]
        # replacing unwanted characters with nan
        if seq_type == 'nu':
            na_values = ['-', 'r', 'y', 'k', 'm', 's', 'w', 'b', 'd', 'h', 'v', 'n']
        else:
            na_values = ['-', 'X', 'B', 'Z', 'J']
        to_replace = []
        for vl in na_values:
            to_replace.append(vl.upper())
            # to_replace.append(vl.lower())
        dat.replace(to_replace, np.nan, inplace=True)
    return dat


# use top categories only:
def balanced_classes(dat, meta_dat, feature):
    tmp = dat.merge(meta_dat[feature], left_index=True, right_index=True)
    vl = tmp[feature].value_counts() / tmp.shape[0]
    categories_to_keep = vl[vl > 1 / len(vl) / 2].index.tolist()
    tmp = tmp[tmp[feature].isin(categories_to_keep)]
    dat = tmp.drop(feature, axis=1)
    return dat


# taking care of missing and constant columns
def missing_constant_care(dat, missing_threshold=0.05):
    tmp = dat.copy()
    threshold = tmp.shape[0] * missing_threshold
    cl = tmp.columns[tmp.isna().sum() > threshold]
    tmp.drop(cl, axis=1, inplace=True)

    cl = tmp.columns[tmp.isnull().sum() > 0]
    tmp2 = tmp[cl]
    tmp.drop(cl, axis=1, inplace=True)
    md = mode(tmp2)[0]

    tmp2 = np.where(pd.isna(tmp2), md, tmp2)
    tmp2 = pd.DataFrame(tmp2, columns=cl, index=tmp.index)
    tmp = pd.concat([tmp, tmp2], axis=1)

    tmp = tmp.loc[:, tmp.nunique() != 1]

    return tmp


# mode = tmp.filter(tmp.columns).mode().iloc[0]  # mode of all the columns
# tmp = tmp.fillna(mode)  # replacing NA values with the mode of each column
# a function which check if one character in a certain column is below a threshold or not
# and replace that character with the mode of that column of merge the rare cases together
def colCleaner_column(dat, column, threshold=0.015):
    vl = dat[column].value_counts()
    ls = vl / dat.shape[0] < threshold
    ls = ls.index[ls == True].tolist()

    if len(ls) > 0:
        if (vl[ls].sum() / dat.shape[0]) < threshold:
            md = vl.index[0]
            dat[column].replace(ls, md, inplace=True)
        else:
            dat[column].replace(ls, ''.join(ls), inplace=True)
    return dat[column]


# taking care of rare cases in columns
def imb_care(dat, imbalance_threshold=0.05):
    tmp = dat.copy()
    for i in range(tmp.shape[1]):
        tmp.iloc[:, i] = colCleaner_column(dat=tmp, column=tmp.columns[i], threshold=imbalance_threshold)
    tmp = tmp.loc[:, tmp.nunique() != 1]
    return tmp


# function to sample from features 
def col_sampler(dat, sample_frac=1):
    if sample_frac < 1:
        samples = int(dat.shape[1] * sample_frac)
        cl = np.random.choice(dat.columns, samples, replace=False).tolist()
        # remove the columns with the n
        dat = dat[cl]
    return dat


# statistical tests to drop redundant positions
def redundant_drop(dat, meta_dat, feature, model_type, report_dir, threshold=0.15):
    """
    This function gets the following variables and performs statistical tests (chi-square or Kruskal–Wallis)
    and based on the p-values and the given threshold, drops redundant positions. A report of all calculated p-values
    will be saved into the given report directory under name of p_values.csv.

    :param dat:
    :param meta_dat:
    :param feature:
    :param model_type:
    :param report_dir:
    :param threshold:
    :return:
    """

    def chisq_test(dat_main, col_list, resp_feature):
        p_val_list = []
        for cl in col_list:
            crs = pd.crosstab(dat_main[cl], dat_main[resp_feature])
            p_val_list.append(chi2_contingency(crs)[1])
        return p_val_list

    def kruskal_test(dat_main, col_list, resp_feature):
        p_val_list = []
        for cl in col_list:
            p_val_list.append(kruskal(*[group[resp_feature].values for name, group in dat_main.groupby(cl)])[1])
        return p_val_list

    tmp = dat.merge(meta_dat[feature], left_index=True, right_index=True)
    cols = dat.columns
    if model_type == 'cl':
        p_val = chisq_test(dat_main=tmp, col_list=cols, resp_feature=feature)
    elif model_type == 'reg':
        p_val = kruskal_test(dat_main=tmp, col_list=cols, resp_feature=feature)
    else:
        raise Exception('Analysis type should be either reg or cl')

    with open(report_dir + "/p_values.csv", "w", newline='') as f:
        writer = csv.writer(f)
        headers = ['position', 'p_value']
        writer.writerow(headers)
        for i in range(len(p_val)):
            content = [cols[i], p_val[i]]
            writer.writerow(content)
    if np.sum(np.array(p_val) < threshold) > 0:
        cols = cols[np.array(p_val) < threshold]
    else:
        cols = cols[np.array(p_val) < np.median(np.array(p_val))]
        print('None of the positions meet the p-value threshold. We selected top 50% positions!')

    return dat.loc[:, cols]


# get dummy variables
def get_dummies(dat, drop_first=True):
    dat = pd.get_dummies(dat, drop_first=drop_first)
    return dat


# function to calculate Cramer's V score
def cramers_V(var1, var2):
    crosstab = np.array(pd.crosstab(var1, var2, rownames=None, colnames=None))  # Cross table building
    stat = chi2_contingency(crosstab)[0]  # Keeping of the test statistic of the Chi2 test
    obs = np.sum(crosstab)  # Number of observations
    mini = min(crosstab.shape) - 1  # Take the minimum value between the columns and the rows of the cross table
    return (stat / (obs * mini))


# function for creating correlation data frame and just report those which are above a treashold
def cor_cal(dat, report_dir, threshold=0.8):
    print('expected_calculations: ', dat.shape[1] * (dat.shape[1] - 1) / 2)
    cn = 0
    cr = pd.DataFrame(columns=['l0', 'l1', 'cor'])
    col_check = []
    for cl in combinations(dat.columns, 2):  # all paired combinations of df columns
        cn += 1
        if cn % 5000 == 0:  # show each 5000 steps
            print(cn)
        cv = cramers_V(dat[cl[0]], dat[cl[1]])
        cr.loc[len(cr)] = [cl[0], cl[1], cv]
        cr.loc[len(cr)] = [cl[1], cl[0], cv]

    cr.to_csv(str(report_dir + '/' + 'correlation_matrix.csv'), index=False)

    return cr  # [cr['cor'] >= threshold]


# a function to calculate adjusted mutual information for all the paired combinations of the dat dataset
def dist_cols(dat, score_func):
    # creating empty dataFrame to keep the results
    cn = 0
    cr = pd.DataFrame(columns=['l0', 'l1', 'cor'])

    for cl in combinations(dat.columns, 2):  # all paired combinations of dat columns

        score = score_func(dat[cl[0]], dat[cl[1]])
        cr.loc[len(cr)] = [cl[0], cl[1], score]
        cr.loc[len(cr)] = [cl[1], cl[0], score]

    cr.loc[cr['cor'] < 0, 'cor'] = 0
    return cr


# create dummy vars, drop those which are below a certain threshold,
# then calculate the similarity between these remaining columns
def ham_dist(dat, threshold=0.2):
    import gc

    # make dummy vars and keep all of them
    tmp1 = pd.get_dummies(dat, drop_first=False)

    # drop rare cases
    cl = tmp1.columns[(tmp1.sum() / dat.shape[0] > threshold)]
    tmp1 = tmp1[cl]

    # creating empty dataFrame to keep the results
    r_nam = tmp1.columns.tolist()
    dis = pd.DataFrame(columns=r_nam, index=r_nam)

    tmp1 = np.array(tmp1).T

    last = range(tmp1.shape[0])
    for i in last:
        dist_vec = (tmp1[0, :] == tmp1).sum(axis=1)

        dis.iloc[i, i:] = dist_vec
        dis.iloc[i:, i] = dist_vec
        tmp1 = np.delete(tmp1, 0, 0)
        if i % 1000 == 0:
            gc.collect()
    gc.collect()
    gc.collect()
    dis = dis / dat.shape[0]
    print('Reset indexes')
    dis.reset_index(inplace=True)
    print('reshaping')
    dis = dis.melt(id_vars='index')
    dis['index'] = dis['index'].str.split('_').str[0]
    dis['variable'] = dis['variable'].str.split('_').str[0]
    gc.collect()
    gc.collect()
    dis = dis[dis['index'] != dis['variable']]
    print('Selecting max values')
    dis = dis.groupby(['index', 'variable']).max().reset_index()
    dis.columns = ['l0', 'l1', 'cor']
    return dis


# calculate vectorized normalized mutual information
def vec_nmi(dat, report_dir):
    # get the sample size
    N = dat.shape[0]
    # create empty dataframe
    dat_temp = pd.DataFrame(columns=dat.columns, index=dat.columns)

    # transpose main dataframe
    df_dum = pd.get_dummies(dat).T.reset_index()
    df_dum[['position', 'char']] = df_dum['index'].str.split("_", expand=True)
    df_dum.drop(['index'], axis=1, inplace=True)

    # total samples within each position with specific character
    col_sum = df_dum.iloc[:, :-2].sum(axis=1)

    # array of all data
    my_array = np.array(df_dum.iloc[:, :-2])

    for name, gr in df_dum.groupby(['position']):
        mu_list = []
        char_list = list(set(df_dum.loc[df_dum.loc[:, 'position'] == name, 'char']))
        temp = df_dum.loc[:, ['position', 'char']]

        for ch in char_list:
            temp.loc[:, 'inter' + ch] = None
            temp.loc[:, 'ui_vi'] = None
            temp.loc[:, 'mui' + ch] = None

            intersects = my_array[(df_dum.loc[:, 'position'] == name) & (df_dum.loc[:, 'char'] == ch)]
            intersects = intersects + my_array
            intersects = intersects == 2

            temp.loc[:, 'inter' + ch] = intersects.sum(axis=1)

            temp.loc[:, 'ui_vi'] = temp.loc[(temp.loc[:, 'position'] == name) & (df_dum.loc[:, 'char'] == ch),
                                     'inter' + ch].values * col_sum
            temp.loc[:, 'mui' + ch] = (temp.loc[:, 'inter' + ch] / N) * (
                np.log(N * (temp.loc[:, 'inter' + ch]) / temp.loc[:, 'ui_vi']))

            mu_list.append('mui' + ch)

        # sum over all entropies
        temp = temp.groupby('position')[mu_list].sum().sum(axis=1)

        # insert into dataframe
        dat_temp[name] = temp

    dat_temp.fillna(0, inplace=True)

    # calculate average entropies
    entropies = np.diag(dat_temp)
    m_entropies = np.tile(entropies, reps=[len(entropies), 1])
    avg_entropies = (entropies.reshape(len(entropies), 1) + m_entropies) / 2

    # calculate normalized mutual information
    dat_temp = dat_temp / avg_entropies
    dat_temp.fillna(0, inplace=True)

    dat_temp.to_csv(str(report_dir + '/' + 'nmi.csv'), index=True)

    return dat_temp


# calculating distance
def distance_calc(dat, dist_method='correlation', report_dir=None):
    method_list = ['correlation', 'hamming', 'jaccard',
                   'normalized_mutual_info_score',
                   'adjusted_mutual_info_score', 'adjusted_rand_score']
    err_msg = "Please choose a distance metric \
    that produces values of |dist|<=1. You can choose any these metrics: {}".format(method_list)

    assert dist_method in method_list, err_msg
    cl_names = dat.columns
    if dist_method == 'correlation':
        dist = abs(abs(1 - squareform(pdist(dat.T, metric='correlation'))) - 1)
    elif dist_method in method_list[-3:]:
        exec('from sklearn.metrics import ' + dist_method)
        dist = abs(squareform(pdist(dat.T, eval(dist_method))))
        np.fill_diagonal(dist, 1)
        dist = 1 - dist
    else:
        dist = abs(squareform(pdist(dat.T, metric=dist_method)))

    dist = pd.DataFrame(dist, columns=cl_names, index=cl_names)

    if report_dir is not None:
        dist.to_csv(str(report_dir + '/' + dist_method + '.csv'), index=True)

    return dist


# grouping features based on DBSCAN clustering algo
def db_grouped(dat, report_dir, threshold=0.2, needs_pivot=False):
    from sklearn.cluster import DBSCAN

    if needs_pivot:
        cr_mat = dat.pivot(index='l0', columns='l1', values='cor')
        cr_mat.fillna(1, inplace=True)
    else:
        cr_mat = dat
#     cr_mat = (cr_mat) ** 2

    db = DBSCAN(eps=threshold, min_samples=2, metric='precomputed', n_jobs=-1)
    db.fit(cr_mat)

    dc_df = pd.DataFrame(cr_mat.index.tolist(), columns=['feature'])
    dc_df['group'] = db.labels_

    clusters = list(set(db.labels_))
    for cluster in clusters:
        if cluster == -1:
            dc_df.loc[dc_df['group'] == -1, 'group'] = 'No_gr'
        else:
            dc_df.loc[dc_df['group'] == cluster, 'group'] = 'g' + str(cluster)
    try:
        dc_df = dc_df[dc_df['group'] != 'No_gr']
    except:
        dc_df = pd.DataFrame(columns=['feature', 'group'])

    dc_df.to_csv(str(report_dir + '/' + 'correlated_positions_DBSCAN.csv'), index=False)
    return dc_df


def col_extract(dat, cl1='l0', cl2='l1'):
    ft_list = dat[cl1].tolist()
    ft_list.extend(dat[cl2].tolist())
    ft_list = list(set(ft_list))
    return ft_list


# function for grouping features in saving them in a dictionary file
def group_features(dat, group_dat, report_dir):
    dc = {}
    if len(dat) > 0:
        for name, gr in group_dat.groupby('group'):
            tmp = group_dat.loc[group_dat['group'] == name, 'feature'].tolist()
            meds = np.array(dat.loc[:, tmp].median(axis=1)).reshape((-1, 1))
            min_s = ((dat.loc[:, tmp] - meds) ** 2).sum().argmin()

            tmp_ar = [tmp[i] for i in range(len(tmp)) if i != min_s]

            dc[tmp[min_s]] = tmp_ar
        dc_temp = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in dc.items()]))
        dc_temp.to_csv(str(report_dir + '/' + 'correlated_positions.csv'), index=False)
    return dc


# function that gets the grouped dictionary and returns a dataframe of grouped features
def group_extend(dic):
    dc_df = pd.DataFrame(columns=['feature', 'group'])
    for n, k in enumerate(dic.keys()):
        ft = dic[k].copy()
        ft.append(k)
        col = [str('g' + str(n))] * len(ft)
        tmp = pd.DataFrame(list(zip(ft, col)), columns=['feature', 'group'])
        dc_df = dc_df.append(tmp, ignore_index=True)
    dc_df['feature'] = dc_df['feature'].str.split('p').str[1]
    dc_df['feature'] = dc_df['feature'].astype(int)
    return dc_df


# function for removing the correlated features from the main dataframe
def cor_remove(dat, dic):
    for k in dic.keys():
        dat.drop(dic[k], axis=1, inplace=True)
    return dat
