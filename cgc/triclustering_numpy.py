import logging

import numpy as np

logger = logging.getLogger(__name__)


def _distance(Z, Y, epsilon):
    """ Distance function """
    Y = Y + epsilon
    return Y.sum(axis=(1, 2)) - np.einsum('ijk,ljk->il', Z, np.log(Y))


def _initialize_clusters(n_el, n_clusters):
    """ Initialize cluster array """
    cluster_idx = np.mod(np.arange(n_el), n_clusters)
    return np.random.permutation(cluster_idx)


def _setup_cluster_matrix(n_clusters, cluster_idx):
    """ Set cluster occupation matrix """
    return np.eye(n_clusters, dtype=np.bool)[cluster_idx]


def triclustering(Z, nclusters_row, nclusters_col, nclusters_bnd, errobj,
                  niters, epsilon, row_clusters_init=None,
                  col_clusters_init=None, bnd_clusters_init=None):
    """
    Run the tri-clustering, Numpy-based implementation

    :param Z: d x m x n data matrix
    :param nclusters_row: number of row clusters
    :param nclusters_col: number of column clusters
    :param nclusters_bnd: number of band clusters
    :param errobj: convergence threshold for the objective function
    :param niters: maximum number of iterations
    :param epsilon: numerical parameter, avoids zero arguments in log
    :param row_clusters_init: initial row cluster assignment
    :param col_clusters_init: initial column cluster assignment
    :param bnd_clusters_init: initial band cluster assignment
    :return: has converged, number of iterations performed, final row,
    column, and band clustering, error value
    """
    [d, m, n] = Z.shape

    # Calculate average
    Gavg = Z.mean()

    # Initialize cluster assignments
    row_clusters = row_clusters_init if row_clusters_init is not None \
        else _initialize_clusters(m, nclusters_row)
    col_clusters = col_clusters_init if col_clusters_init is not None \
        else _initialize_clusters(n, nclusters_col)
    bnd_clusters = bnd_clusters_init if bnd_clusters_init is not None \
        else _initialize_clusters(d, nclusters_bnd)

    e, old_e = 2 * errobj, 0
    s = 0
    converged = False

    while (not converged) & (s < niters):
        logger.debug(f'Iteration # {s} ..')
        # Calculate number of elements in each tri-cluster
        nel_row_clusters = np.bincount(row_clusters, minlength=nclusters_row)
        nel_col_clusters = np.bincount(col_clusters, minlength=nclusters_col)
        nel_bnd_clusters = np.bincount(bnd_clusters, minlength=nclusters_bnd)
        logger.debug(
            'num of populated clusters: row {}, col {}, bnd {}'.format(
                np.sum(nel_row_clusters > 0),
                np.sum(nel_col_clusters > 0),
                np.sum(nel_bnd_clusters > 0)
            )
        )
        nel_clusters = np.einsum('i,j->ij', nel_row_clusters, nel_col_clusters)
        nel_clusters = np.einsum('i,jk->ijk', nel_bnd_clusters, nel_clusters)

        R = _setup_cluster_matrix(nclusters_row, row_clusters)
        C = _setup_cluster_matrix(nclusters_col, col_clusters)
        B = _setup_cluster_matrix(nclusters_bnd, bnd_clusters)

        # calculate tri-cluster averages (epsilon takes care of empty clusters)
        # first sum values in each tri-cluster ..
        TriCavg = np.einsum('ij,ilm->jlm', B, Z)  # .. along band axis
        TriCavg = np.einsum('ij,kim->kjm', R, TriCavg)  # .. along row axis
        TriCavg = np.einsum('ij,kli->klj', C, TriCavg)  # .. along col axis
        # finally divide by number of elements in each tri-cluster
        TriCavg = (TriCavg + Gavg * epsilon) / (nel_clusters + epsilon)

        # unpack tri-cluster averages ..
        avg_unpck = np.einsum('ij,jkl->ikl', B, TriCavg)  # .. along band axis
        avg_unpck = np.einsum('ij,klj->kli', C, avg_unpck)  # .. along col axis
        # use these for the row cluster assignment
        idx = (1, 0, 2)
        d_row = _distance(Z.transpose(idx), avg_unpck.transpose(idx), epsilon)
        row_clusters = np.argmin(d_row, axis=1)

        # unpack tri-cluster averages ..
        avg_unpck = np.einsum('ij,jkl->ikl', B, TriCavg)  # .. along band axis
        avg_unpck = np.einsum('ij,kjl->kil', R, avg_unpck)  # .. along row axis
        # use these for the col cluster assignment
        idx = (2, 0, 1)
        d_col = _distance(Z.transpose(idx), avg_unpck.transpose(idx), epsilon)
        col_clusters = np.argmin(d_col, axis=1)

        # unpack tri-cluster averages ..
        avg_unpck = np.einsum('ij,kjl->kil', R, TriCavg)  # .. along row axis
        avg_unpck = np.einsum('ij,klj->kli', C, avg_unpck)  # .. along col axis
        # use these for the band cluster assignment
        d_bnd = _distance(Z, avg_unpck, epsilon)
        bnd_clusters = np.argmin(d_bnd, axis=1)

        # Error value (actually just the band component really)
        old_e = e
        minvals = np.min(d_bnd, axis=1)
        # power 1 divergence, power 2 euclidean
        e = np.sum(np.power(minvals, 1))

        logger.debug(f'Error = {e:+.15e}, dE = {e - old_e:+.15e}')
        converged = abs(e - old_e) < errobj
        s = s + 1
    if converged:
        logger.debug(f'Triclustering converged in {s} iterations')
    else:
        logger.debug(f'Triclustering not converged in {s} iterations')
    return converged, s, row_clusters, col_clusters, bnd_clusters, e
