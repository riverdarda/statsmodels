"""
Methods for analyzing contingency tables.
"""

from __future__ import division
from statsmodels.tools.decorators import cache_readonly, resettable_cache
import numpy as np
from scipy import stats
import pandas as pd
from statsmodels import iolib

def _handle_pandas_square(table):
    """
    Reindex a pandas table so that it becomes square (extending the
    row and column index as needed).
    """

    if not isinstance(table, pd.DataFrame):
        return table

    # If the table is not square, make it square
    if table.shape[0] != table.shape[1]:
        ix = list(set(table.index) | set(table.columns))
        table = table.reindex(ix, axis=0)
        table = table.reindex(ix, axis=1)

    return table

class _bunch(object):
    pass


class TableSymmetry(object):
    """
    Methods for analyzing a square contingency table.

    Parameters
    ----------
    table : array-like
        A contingency table.

    These methods should only be used when the rows and columns of the
    table have the same categories.  If `table` is provided as a
    Pandas array, the row and column indices will be extended to
    create a square table.  Otherwise the table should be provided in
    a square form, with the (implicit) row and column categories
    appearing in the same order.
    """

    def __init__(self, table):
        table = _handle_pandas_square(table)
        table = np.asarray(table, dtype=np.float64)
        k, k2 = table.shape
        if k != k2:
            raise ValueError('table must be square')
        self._table = table


    @classmethod
    def from_data(cls, data):
        """
        Construct a TableSymmetry object from data.

        Parameters
        ----------
        data : array-like
            The raw data, from which a cross-table is constructed
            using the first two columns.

        Returns
        -------
        A TableSymmetry instance.
        """

        if isinstance(data, pd.DataFrame):
            table = pd.crosstab(data.iloc[:, 0], data.iloc[:, 1])
        else:
            table = pd.crosstab(data[:, 0], data[:, 1])

        return cls(table)


    def symmetry(self, method="bowker"):
        """
        Test for symmetry of a joint distribution.

        This procedure tests the null hypothesis that the joint
        distribution is symmetric around the main diagonal, that is

        .. math::

        p_{i, j} = p_{j, i}  for all i, j

        Returns
        -------
        statistic : float
            chisquare test statistic
        p-value : float
            p-value of the test statistic based on chisquare distribution
        df : int
            degrees of freedom of the chisquare distribution

        Notes
        -----
        The implementation is based on the SAS documentation. R includes
        it in `mcnemar.test` if the table is not 2 by 2.  However a more
        direct generalization of the McNemar test to large tables is
        provided by the homogeneity test (TableSymmetry.homogeneity).

        The p-value is based on the chi-square distribution which requires
        that the sample size is not very small to be a good approximation
        of the true distribution. For 2x2 contingency tables the exact
        distribution can be obtained with `mcnemar`

        See Also
        --------
        mcnemar
        homogeneity
        """

        if method.lower() != "bowker":
            raise ValueError("method for symmetry testing must be 'bowker'")

        k = self._table.shape[0]
        upp_idx = np.triu_indices(k, 1)

        tril = self._table.T[upp_idx]   # lower triangle in column order
        triu = self._table[upp_idx]     # upper triangle in row order

        stat = ((tril - triu)**2 / (tril + triu + 1e-20)).sum()
        df = k * (k-1) / 2.
        pval = stats.chi2.sf(stat, df)

        return stat, pval, df


    def homogeneity(self, method="stuart_maxwell"):
        """
        Compare row and column marginal distributions.

        Parameters
        ----------
        method : string
            Either 'stuart_maxwell' or 'bhapkar', leading to two different
            estimates of the covariance matrix for the estimated
            difference between the row margins and the column margins.

        Returns
        -------
        stat : float
            The chi^2 test statistic
        pvalue : float
            The p-value of the test statistic
        df : integer
            The degrees of freedom of the reference distribution

        Notes
        -----
        For a 2x2 table this is equivalent to McNemar's test.  More
        generally the procedure tests the null hypothesis that the
        marginal distribution of the row factor is equal to the marginal
        distribution of the column factor.  For this to be meaningful, the
        two factors must have the same sample space.
        """

        if self._table.shape[0] < 1:
            raise ValueError('table is empty')
        elif self._table.shape[0] == 1:
            return 0., 1., 0

        method = method.lower()
        if method not in ["bhapkar", "stuart_maxwell"]:
            raise ValueError("method '%s' for homogeneity not known" % method)

        n_obs = self._table.sum()
        pr = self._table.astype(np.float64) / n_obs

        # Compute margins, eliminate last row/column so there is no
        # degeneracy
        row = pr.sum(1)[0:-1]
        col = pr.sum(0)[0:-1]
        pr = pr[0:-1, 0:-1]

        # The estimated difference between row and column margins.
        d = col - row

        # The degrees of freedom of the chi^2 reference distribution.
        df = pr.shape[0]

        if method == "bhapkar":
            vmat = -(pr + pr.T) - np.outer(d, d)
            dv = col + row - 2*np.diag(pr) - d**2
            np.fill_diagonal(vmat, dv)
        elif method == "stuart_maxwell":
            vmat = -(pr + pr.T)
            dv = row + col - 2*np.diag(pr)
            np.fill_diagonal(vmat, dv)

        try:
            stat = n_obs * np.dot(d, np.linalg.solve(vmat, d))
        except np.linalg.LinAlgError:
            warnings.warn("Unable to invert covariance matrix")
            return np.nan, np.nan, df

        pvalue = 1 - stats.chi2.cdf(stat, df)

        return stat, pvalue, df


    def summary(self, alpha=0.05, float_format="%.3f"):

        fmt = float_format

        headers = ["Statistic", "P-value", "DF"]
        stubs = ["Symmetry", "Homogeneity"]
        stat1, pvalue1, df1 = self.symmetry()
        stat2, pvalue2, df2 = self.homogeneity()
        data = [[fmt % stat1, fmt % pvalue1, '%d' % df1],
                [fmt % stat2, fmt % pvalue2, '%d' % df2]]
        tab = iolib.SimpleTable(data, headers, stubs, data_aligns="r",
                                 table_dec_above='')

        return tab


class TableAssociation(object):
    """
    Assess row/column association in a contingency table.

    Parameters
    ----------
    table : array-like
        A contingency table.
    method : string
        Method for conducting the association test.  Must be either
        `Pearson` for a Pearson chi^2 test or `lbl` for a
        linear-by-linear association test.
    row_scores : array-like
        Optional row scores for ordinal rows.
    col_scores : array-like
        Optional column scores for ordinal columns.

    Notes
    -----
    Using the default row and column scores for the linear-by-linear
    association test gives the Cochran-Armitage trend test.

    See also
    --------
    statsmodels.graphics.mosaicplot.mosaic
    scipy.stats.chi2_contingency
    """

    def __init__(self, table, method='chi2', row_scores=None, col_scores=None):

        table = np.asarray(table, dtype=np.float64)
        self._table = table

        method = method.lower()
        if method == 'lbl':

            if row_scores is None:
                row_scores = np.arange(table.shape[0])
            if col_scores is None:
                col_scores = np.arange(table.shape[1])

            if len(row_scores) != table.shape[0]:
                raise ValueError("The length of `row_scores` must match the first dimension of `table`.")

            if len(col_scores) != table.shape[1]:
                raise ValueError("The length of `col_scores` must match the second dimension of `table`.")

            if row_scores is not None:
                self._row_scores = row_scores
            if col_scores is not None:
                self._col_scores = col_scores

            self._ordinal_association()

        elif method == 'chi2':
            self._chi2_association()

        else:
            raise ValueError('uknown association method')


    def _ordinal_association(self):

        # The test statistic
        stat = np.dot(self._row_scores, np.dot(self._table, self._col_scores))

        # Some needed quantities
        n_obs = self._table.sum()
        rtot = self._table.sum(1)
        um = np.dot(self._row_scores, rtot)
        u2m = np.dot(self._row_scores**2, rtot)
        ctot = self._table.sum(0)
        vn = np.dot(self._col_scores, ctot)
        v2n = np.dot(self._col_scores**2, ctot)

        # The null mean and variance of the test statistic
        e_stat = um * vn / n_obs
        v_stat = (u2m - um**2 / n_obs) * (v2n - vn**2 / n_obs) / (n_obs - 1)
        sd_stat = np.sqrt(v_stat)

        zscore = (stat - e_stat) / sd_stat
        pvalue = 2 * stats.norm.cdf(-np.abs(zscore))

        self._stat = stat
        self._stat_e0 = e_stat
        self._stat_sd0 = sd_stat
        self._zscore = zscore
        self._pvalue = pvalue


    def _chi2_association(self):

        contribs = self.chi2_contribs
        self._stat = contribs.sum()
        df = np.prod(np.asarray(self._table.shape) - 1)
        self._pvalue = 1 - stats.chi2.cdf(self._stat, df)


    @cache_readonly
    def marginal_probabilities(self):
        """
        Return the estimated row and column marginal distributions.
        """
        n = self._table.sum()
        row = self._table.sum(1) / n
        col = self._table.sum(0) / n
        return row, col


    @cache_readonly
    def independence_probabilities(self):
        """
        Estimated cell probabilities under independence.
        """
        row, col = self.marginal_probabilities
        return np.outer(row, col)


    @cache_readonly
    def fitted_values(self):
        """
        Fitted values under independence.
        """
        probs = self.independence_probabilities
        fit = self._table.sum() * probs
        return fit


    @cache_readonly
    def pearson_resids(self):
        """
        The Pearson residuals.
        """
        fit = self.fitted_values
        resids = (self._table - fit) / np.sqrt(fit)
        return resids


    @cache_readonly
    def standardized_resids(self):
        """
        Residuals with unit variance.
        """
        row, col = self.marginal_probabilities
        sresids = self.resids / np.sqrt(np.outer(1 - row, 1 - col))
        return sresids


    @cache_readonly
    def chi2_contribs(self):
        """
        The contribution of each cell to the chi^2 statistic.
        """
        return self.pearson_resids**2


    @cache_readonly
    def pvalue(self):
        """
        The p-value of the association test.
        """
        return self._pvalue


    @cache_readonly
    def zscore(self):
        """
        The Z-score of the association test statistic.

        Only defined if the LBL method is used.
        """
        return self._zscore


    @cache_readonly
    def stat(self):
        """
        The association test statistic.
        """
        return self._stat


    @cache_readonly
    def stat_e0(self):
        """
        Returns the null mean of the test statistic.

        Only defined if the linear-by-linear (LBL) association test is
        used.
        """
        return self._stat_e0


    @cache_readonly
    def stat_sd0(self):
        """
        Returns the null standard deviation of the test statistic.

        Only defined if the linear-by-linear (LBL) association test is
        used.
        """
        return self._stat_sd0


class Table2x2(object):
    """
    Analyses that can be performed on a single 2x2 table.

    Note that for the risk ratio, the analysis is not symmetric with
    respect to the rows and columns of the contingency table.  The two
    rows define population subgroups, column 0 is the number of
    'events', and column 1 is the number of 'non-events'.

    Parameters
    ----------
    table : array-like
        A 2x2 contingency table
    shift_zeros : boolean
        If true, 0.5 is added to all cells of the table if any cell is
        equal to zero.
    """

    def __init__(self, table, shift_zeros=True):

        table = np.asarray(table, dtype=np.float64)
        if (table.ndim != 2) or (table.shape[0] != 2) or (table.shape[1] != 2):
            raise ValueError("Table2x2 takes a 2x2 table as input.")

        if shift_zeros and (table.min() == 0):
            table = table + 0.5

        self._table = table


    @cache_readonly
    def log_oddsratio(self):
        """
        The log odds ratio of the table.
        """
        f = self._table.flatten()
        return np.dot(np.log(f), np.r_[1, -1, -1, 1])


    @cache_readonly
    def oddsratio(self):
        """
        The odds ratio of the table.
        """
        return self._table[0, 0] * self._table[1, 1] / (self._table[0, 1] * self._table[1, 0])


    @cache_readonly
    def log_oddsratio_se(self):
        """
        The asymptotic standard error of the estimated log odds ratio.
        """
        return np.sqrt(np.sum(1 / self._table))


    @cache_readonly
    def oddsratio_pvalue(self):
        """
        P-value for the null hypothesis that the odds ratio equals 1.
        """
        zscore = self.log_oddsratio / self.log_oddsratio_se
        pvalue = 2 * stats.norm.cdf(-np.abs(zscore))
        return pvalue


    @cache_readonly
    def log_oddsratio_pvalue(self):
        """
        P-value for the null hypothesis that the log odds ratio equals zero.
        """
        return self.oddsratio_pvalue


    def log_oddsratio_confint(self, alpha):
        """
        A confidence level for the log odds ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            confidence interval.
        """
        f = -stats.norm.ppf(alpha / 2)
        lor = self.log_oddsratio
        se = self.log_oddsratio_se
        lcb = lor - f * se
        ucb = lor + f * se
        return lcb, ucb


    def oddsratio_confint(self, alpha):
        """
        A confidence interval for the odds ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            confidence interval.
        """
        lcb, ucb = self.log_oddsratio_confint(alpha)
        return np.exp(lcb), np.exp(ucb)


    @cache_readonly
    def riskratio(self):
        """
        The estimated risk ratio for the table.

        Returns the ratio between the risk in the first row and the
        risk in the second row.  Column 0 is interpreted as containing
        the number of occurances of the event of interest.
        """
        p = self._table[:, 0] / self._table.sum(1)
        return p[0] / p[1]


    @cache_readonly
    def log_riskratio(self):
        """
        The estimated log risk ratio for the table.
        """
        return np.log(self.riskratio)


    @cache_readonly
    def log_riskratio_se(self):
        """
        The standard error of the estimated log risk ratio for the table.
        """
        n = self._table.sum(1)
        p = self._table[:, 0] / n
        va = np.sum((1 - p) / (n*p))
        return np.sqrt(va)


    @cache_readonly
    def riskratio_pvalue(self):
        """
        p-value for the null hypothesis that the risk ratio equals 1.
        """
        zscore = self.log_riskratio / self.log_riskratio_se
        pvalue = 2 * stats.norm.cdf(-np.abs(zscore))
        return pvalue


    @cache_readonly
    def log_riskratio_pvalue(self):
        """
        p-value for the null hypothesis that the log risk ratio equals 0.
        """
        return self.riskratio_pvalue


    def log_riskratio_confint(self, alpha):
        """
        A confidence interval for the log risk ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            confidence interval.
        """
        f = -stats.norm.ppf(alpha / 2)
        lrr = self.log_riskratio
        se = self.log_riskratio_se
        lcb = lrr - f * se
        ucb = lrr + f * se
        return lcb, ucb


    def riskratio_confint(self, alpha):
        """
        A confidence interval for the risk ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            confidence interval.
        """
        lcb, ucb = self.log_riskratio_confint(alpha)
        return np.exp(lcb), np.exp(ucb)


    @classmethod
    def from_data(cls, var1, var2, data, shift_zeros=True):
        """
        Construct a Table2x2 object from data.

        Parameters
        ----------
        var1 : string
            Name or column index of the first variable, defining the
            rows.
        var2 : string
            Name or column index of the first variable, defining the
            columns.
        data : array-like
            The raw data.
        shift_zeros : boolean
            If True, and if there are any zeros in the contingency
            table, add 0.5 to all four cells of the table.

        Notes
        -----
        The columns used to produce the contingency table must each
        have two distinct values.
        """

        if isinstance(data, pd.DataFrame):
            table = pd.crosstab(data.loc[:, var1], data.loc[:, var2])
        else:
            table = pd.crosstab(data[:, var1], data[:, var2])
        return cls(table, shift_zeros)


    def summary(self, alpha=0.05, float_format="%.3f"):
        """
        Summarizes results for a 2x2 table analysis.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the confidence
            intervals.
        """

        def fmt(x):
            if type(x) is str:
                return x
            return float_format % x

        headers = ["Estimate", "SE", "LCB", "UCB", "p-value"]
        stubs = ["Odds ratio", "Log odds ratio", "Risk ratio", "Log risk ratio"]

        lcb1, ucb1 = self.oddsratio_confint(alpha)
        lcb2, ucb2 = self.log_oddsratio_confint(alpha)
        lcb3, ucb3 = self.riskratio_confint(alpha)
        lcb4, ucb4 = self.log_riskratio_confint(alpha)
        data = [[fmt(x) for x in [self.oddsratio, "", lcb1, ucb1, self.oddsratio_pvalue]],
                [fmt(x) for x in [self.log_oddsratio, self.log_oddsratio_se, lcb2, ucb2,
                                  self.oddsratio_pvalue]],
                [fmt(x) for x in [self.riskratio, "", lcb2, ucb2, self.riskratio_pvalue]],
                [fmt(x) for x in [self.log_riskratio, self.log_riskratio_se, lcb4, ucb4,
                                  self.riskratio_pvalue]]]
        tab = iolib.SimpleTable(data, headers, stubs, data_aligns="r",
                                table_dec_above='')
        return tab



class StratifiedTables(object):
    """
    Analyses for a collection of 2x2 stratified contingency tables.

    This class implements the 'Cochran-Mantel-Haenszel' and
    'Breslow-Day' procedures for analyzing collections of 2x2
    contingency tables.

    Parameters
    ----------
    tables : list
        A list containing 2x2 contingency tables.
    """

    def __init__(self, tables, shift_zeros=False):

        # Create a data cube
        tables = [np.asarray(x) for x in tables]
        table = [x[:, :, None] for x in tables]
        table = np.concatenate(table, axis=2).astype(np.float64)

        if shift_zeros:
            zx = (table == 0).sum(0).sum(0)
            ix = np.flatnonzero(zx > 0)
            if len(ix) > 0:
                table[:, :, ix] += 0.5

        self._table = table

        self._cache = resettable_cache()

        # Quantities to precompute.  Table entries are [[a, b], [c,
        # d]], 'ad' is 'a * d', 'apb' is 'a + b', 'dma' is 'd - a',
        # etc.
        self._apb = table[0, 0, :] + table[0, 1, :]
        self._apc = table[0, 0, :] + table[1, 0, :]
        self._bpd = table[0, 1, :] + table[1, 1, :]
        self._cpd = table[1, 0, :] + table[1, 1, :]
        self._ad = table[0, 0, :] * table[1, 1, :]
        self._bc = table[0, 1, :] * table[1, 0, :]
        self._apd = table[0, 0, :] + table[1, 1, :]
        self._dma = table[1, 1, :] - table[0, 0, :]
        self._n = table.sum(0).sum(0)


    @classmethod
    def from_data(cls, var1, var2, strata, data):
        """
        Construct a StratifiedTables object from data.

        Parameters
        ----------
        var1 : int or string
            The column index or name of `data` containing the variable
            defining the rows of the contingency table.  The variable
            must have only two distinct values.
        var2 : int or string
            The column index or name of `data` containing the variable
            defining the columns of the contingency table.  The variable
            must have only two distinct values.
        strata : int or string
            The column index of name of `data` containing the variable
            defining the strata.
        data : array-like
            The raw data.  A cross-table for analysis is constructed
            from the first two columns.

        Returns
        -------
        A StratifiedTables instance.
        """

        if not isinstance(data, pd.DataFrame):
            data1 = pd.DataFrame(index=data.index, column=[var1, var2, strata])
            data1.loc[:, var1] = data[:, var1]
            data1.loc[:, var2] = data[:, var2]
            data1.loc[:, strata] = data[:, strata]
        else:
            data1 = data

        gb = data1.groupby(strata).groups
        tables = []
        for g in gb:
            ii = gb[g]
            tab = pd.crosstab(data1.loc[ii, var1], data1.loc[ii, var2])
            tables.append(tab)
        return cls(tables)


    def test_null_odds(self, correction=False):
        """
        Test that all tables have odds ratio equal to 1.

        This is the 'Mantel-Haenszel' test.

        Parameters
        ----------
        correction : boolean
            If True, use the continuity correction when calculating the
            test statistic.

        Returns the chi^2 test statistic and p-value.
        """

        stat = np.sum(self._table[0, 0, :] - self._apb * self._apc / self._n)
        stat = np.abs(stat)
        if correction:
            stat -= 0.5
        stat = stat**2
        denom = self._apb * self._apc * self._bpd * self._cpd
        denom /= (self._n**2 * (self._n - 1))
        denom = np.sum(denom)
        stat /= denom

        # df is always 1
        pvalue = 1 - stats.chi2.cdf(stat, 1)

        return stat, pvalue


    @cache_readonly
    def common_odds(self):
        """
        An estimate of the common odds ratio.

        This is the Mantel-Haenszel estimate of an odds ratio that is
        common to all tables.
        """

        odds_ratio = np.sum(self._ad / self._n) / np.sum(self._bc / self._n)
        return odds_ratio


    @cache_readonly
    def common_logodds(self):
        """
        An estimate of the common log odds ratio.

        This is the Mantel-Haenszel estimate of a risk ratio that is
        common to all the tables.
        """

        return np.log(self.common_odds)


    @cache_readonly
    def common_risk(self):
        """
        An estimate of the common risk ratio.

        This is an estimate of a risk ratio that is common to all the
        tables.
        """

        acd = self._table[0, 0, :] * self._cpd
        cab = self._table[1, 0, :] * self._apb

        rr = np.sum(acd / self._n) / np.sum(cab / self._n)
        return rr


    @cache_readonly
    def common_logodds_se(self):
        """
        The estimated standard error of the common log odds ratio.

        References
        ----------
        Robins, Breslow and Greenland (Biometrics, 42:311–323)
        """

        adns = np.sum(self._ad / self._n)
        bcns = np.sum(self._bc / self._n)
        lor_va = np.sum(self._apd * self._ad / self._n**2) / adns**2
        mid = self._apd * self._bc / self._n**2
        mid += (1 - self._apd / self._n) * self._ad / self._n
        mid = np.sum(mid)
        mid /= (adns * bcns)
        lor_va += mid
        lor_va += np.sum((1 - self._apd / self._n) * self._bc / self._n) / bcns**2
        lor_va /= 2
        lor_se = np.sqrt(lor_va)
        return lor_se


    def common_logodds_confint(self, alpha=0.05):
        """
        A confidence interval for the common log odds ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            interval.

        Returns
        -------
        lcb : float
            The lower confidence limit.
        ucb : float
            The upper confidence limit.
        """

        lor = np.log(self.common_odds)
        lor_se = self.common_logodds_se

        f = -stats.norm.ppf(alpha / 2)

        lcb = lor - f * lor_se
        ucb = lor + f * lor_se

        return lcb, ucb


    def common_odds_confint(self, alpha=0.05):
        """
        A confidence interval for the common odds ratio.

        Parameters
        ----------
        alpha : float
            `1 - alpha` is the nominal coverage probability of the
            interval.

        Returns
        -------
        lcb : float
            The lower confidence limit.
        ucb : float
            The upper confidence limit.
        """

        lcb, ucb = self.common_logodds_confint(alpha)
        lcb = np.exp(lcb)
        ucb = np.exp(ucb)
        return lcb, ucb


    def test_equal_odds(self, adjust=False):
        """
        Test that all odds ratios are identical.

        This is the 'Breslow-Day' testing procedure.

        Parameters
        ----------
        adjust : boolean
            Use the 'Tarone' adjustment to achieve the chi^2
            asymptotic distribution.

        Returns the test statistic and p-value.
        """

        table = self._table

        r = self.common_odds
        a = 1 - r
        b = r * (self._apb + self._apc) + self._dma
        c = -r * self._apb * self._apc

        # Expected value of first cell
        e11 = (-b + np.sqrt(b**2 - 4*a*c)) / (2*a)

        # Variance of the first cell
        v11 = 1 / e11 + 1 / (self._apc - e11) + 1 / (self._apb - e11) + 1 / (self._dma + e11)
        v11 = 1 / v11

        stat = np.sum((table[0, 0, :] - e11)**2 / v11)

        if adjust:
            adj = table[0, 0, :].sum() - e11.sum()
            adj = adj**2
            adj /= np.sum(v11)
            stat -= adj

        pvalue = 1 - stats.chi2.cdf(stat, table.shape[2] - 1)

        return stat, pvalue


    def summary(self, alpha=0.05, float_format="%.3f"):
        """
        A summary of all the main results.
        """

        def fmt(x):
            if type(x) is str:
                return x
            return float_format % x

        co_lcb, co_ucb = self.common_odds_confint(alpha=alpha)
        clo_lcb, clo_ucb = self.common_logodds_confint(alpha=alpha)
        headers = ["Estimate", "LCB", "UCB"]
        stubs = ["Common odds", "Common log odds", "Common risk ratio", ""]
        data = [[fmt(x) for x in [self.common_odds, co_lcb, co_ucb]],
                [fmt(x) for x in [self.common_logodds, clo_lcb, clo_ucb]],
                [fmt(x) for x in [self.common_risk, "", ""]],
                ['', '', '']]
        tab1 = iolib.SimpleTable(data, headers, stubs, data_aligns="r",
                                 table_dec_above='')

        headers = ["Statistic", "P-value", ""]
        stubs = ["Test of OR=1", "Test constant OR"]
        stat1, pvalue1 = self.test_null_odds()
        stat2, pvalue2 = self.test_equal_odds()
        data = [[fmt(x) for x in [stat1, pvalue1, ""]],
                [fmt(x) for x in [stat2, pvalue2, ""]]]
        tab2 = iolib.SimpleTable(data, headers, stubs, data_aligns="r")
        tab1.extend(tab2)

        headers = ["", "", ""]
        stubs = ["Number of tables", "Min n", "Max n", "Avg n", "Total n"]
        stat1, pvalue1 = self.test_null_odds()
        stat2, pvalue2 = self.test_equal_odds()
        ss = self._table.sum(0).sum(0)
        data = [["%d" % self._table.shape[2], '', ''],
                ["%d" % min(ss), '', ''],
                ["%d" % max(ss), '', ''],
                ["%.0f" % np.mean(ss), '', ''],
                ["%d" % sum(ss), '', '', '']]
        tab3 = iolib.SimpleTable(data, headers, stubs, data_aligns="r")
        tab1.extend(tab3)

        return tab1



def mcnemar(table, exact=True, correction=True):
    """
    McNemar test of homogeneity.

    Parameters
    ----------
    table : array-like
        A square contingency table.
    exact : bool
        If exact is true, then the binomial distribution will be used.
        If exact is false, then the chisquare distribution will be
        used, which is the approximation to the distribution of the
        test statistic for large sample sizes.
    correction : bool
        If true, then a continuity correction is used for the chisquare
        distribution (if exact is false.)

    Returns
    -------
    stat : float or int, array
        The test statistic is the chisquare statistic if exact is
        false. If the exact binomial distribution is used, then this
        contains the min(n1, n2), where n1, n2 are cases that are zero
        in one sample but one in the other sample.
    pvalue : float or array
        p-value of the null hypothesis of equal marginal distributions.

    Notes
    -----
    This is a special case of Cochran's Q test, and of the homogeneity
    test. The results when the chisquare distribution is used are
    identical, except for continuity correction.
    """

    table = _handle_pandas_square(table)
    table = np.asarray(table, dtype=np.float64)
    n1, n2 = table[0, 1], table[1, 0]

    if exact:
        stat = np.minimum(n1, n2)
        # binom is symmetric with p=0.5
        pval = stats.binom.cdf(stat, n1 + n2, 0.5) * 2
        pval = np.minimum(pval, 1)  # limit to 1 if n1==n2
    else:
        corr = int(correction) # convert bool to 0 or 1
        stat = (np.abs(n1 - n2) - corr)**2 / (1. * (n1 + n2))
        df = 1
        pval = stats.chi2.sf(stat, df)
    return stat, pval


def cochrans_q(x, return_object=True):
    """
    Cochran's Q test for identical binomial proportions.

    Parameters
    ----------
    x : array_like, 2d (N, k)
        data with N cases and k variables
    return_object : boolean
        Return values as bunch instead of as individual values.

    Returns
    -------
    Returns a bunch containing the following attributes, or the
    individual values according to the value of `return_object`.

    q_stat : float
       test statistic
    pvalue : float
       pvalue from the chisquare distribution

    Notes
    -----
    Cochran's Q is a k-sample extension of the McNemar test. If there
    are only two groups, then Cochran's Q test and the McNemar test
    are equivalent.

    The procedure tests that the probability of success is the same
    for every group.  The alternative hypothesis is that at least two
    groups have a different probability of success.

    In Wikipedia terminology, rows are blocks and columns are
    treatments.  The number of rows N, should be large for the
    chisquare distribution to be a good approximation.

    The Null hypothesis of the test is that all treatments have the
    same effect.

    References
    ----------
    http://en.wikipedia.org/wiki/Cochran_test
    SAS Manual for NPAR TESTS
    """

    x = np.asarray(x, dtype=np.float64)
    gruni = np.unique(x)
    N, k = x.shape
    count_row_success = (x == gruni[-1]).sum(1, float)
    count_col_success = (x == gruni[-1]).sum(0, float)
    count_row_ss = count_row_success.sum()
    count_col_ss = count_col_success.sum()
    assert count_row_ss == count_col_ss  #just a calculation check

    # From the SAS manual
    q_stat = (k-1) * (k *  np.sum(count_col_success**2) - count_col_ss**2) \
             / (k * count_row_ss - np.sum(count_row_success**2))

    # Note: the denominator looks just like k times the variance of
    # the columns

    # Wikipedia uses a different, but equivalent expression
    #q_stat = (k-1) * (k *  np.sum(count_row_success**2) - count_row_ss**2) \
    #         / (k * count_col_ss - np.sum(count_col_success**2))

    df = k - 1
    pvalue = stats.chi2.sf(q_stat, df)

    if return_object:
        b = _bunch()
        b.stat = q_stat
        b.df = df
        b.pvalue = pvalue
        return b

    return q_stat, pvalue, df
