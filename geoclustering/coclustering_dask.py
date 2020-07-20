import numpy as np

import dask.array as da
from dask.distributed import get_client


def _distance(Z, X, Y, epsilon):
    """ Distance function """
    Y = Y + epsilon
    d = da.dot(X, Y) - da.dot(Z, da.log(Y))
    return d


def _initialize_clusters(n_el, n_clusters):
    """ Initialize cluster occupation matrix """
    cluster_idx = da.mod(da.arange(n_el), n_clusters)
    cluster_idx = da.random.permutation(cluster_idx)
    # TODO: check if Z shape is larger than max int32?
    eye = da.eye(n_clusters, dtype=np.int32)
    return eye[cluster_idx]


def coclustering(Z, k, l, errobj, niters, epsilon):
    """
    Run the co-clustering, Dask implementation

    :param Z: m x n data matrix
    :param k: num row clusters
    :param l: num col clusters
    :param errobj: precision of obj fun for convergence
    :param niters: max iterations
    :param epsilon: precision of matrix elements
    :return: has converged, number of iterations performed. final row and
    column clustering, error value
    """
    client = get_client()

    [m, n] = Z.shape

    R = _initialize_clusters(m, k)
    C = _initialize_clusters(n, l)

    e, old_e = 2 * errobj, 0
    s = 0
    converged = False

    Gavg = Z.mean()

    while (not converged) & (s < niters):
        # Calculate cluster based averages
        CoCavg = (da.dot(da.dot(R.T, Z), C) + Gavg * epsilon) / (
            da.dot(da.dot(R.T, da.ones((m, n))), C) + epsilon)

        # Calculate distance based on row approximation
        d_row = _distance(Z, da.ones((m, n)), da.dot(C, CoCavg.T), epsilon)
        # Assign to best row cluster
        row_clusters = da.argmin(d_row, axis=1)
        R = da.eye(k, dtype=np.int32)[row_clusters]

        # Calculate distance based on column approximation
        d_col = _distance(Z.T, da.ones((n, m)), da.dot(R, CoCavg), epsilon)
        # Assign to best column cluster
        col_clusters = da.argmin(d_col, axis=1)
        C = da.eye(l, dtype=np.int32)[col_clusters]

        # Error value (actually just the column components really)
        old_e = e
        minvals = da.min(d_col, axis=1)
        # power 1 divergence, power 2 euclidean
        e = da.sum(da.power(minvals, 1))
        row_clusters, col_clusters, e = client.persist([row_clusters,
                                                        col_clusters,
                                                        e])

        converged = abs(e - old_e) < errobj
        s = s + 1

    return converged, s, row_clusters, col_clusters, e
