import concurrent.futures
import copy
import dask.distributed
import logging

from concurrent.futures import ThreadPoolExecutor
from dask.distributed import Client

from . import coclustering_dask
from . import coclustering_numpy

from .results import Results

logger = logging.getLogger(__name__)


class CoclusteringResults(Results):
    """
    Contains results and metadata of a co-clustering calculation.

    :param input_parameters: Input arguments to
        :class:`cgc.coclustering.Coclustering`.
    :type input_parameters: dict
    :var row_clusters: Final row cluster assignment.
    :vartype row_clusters: numpy.ndarray
    :var col_clusters: Final column cluster assignment.
    :vartype col_clusters: numpy.ndarray
    :var error: Approximation error of the co-clustering.
    :vartype error: float
    :var nruns_completed: Number of successfully completed runs.
    :vartype nruns_completed: int
    :var nruns_converged: Number of converged runs.
    :vartype nruns_converged: int
    """
    def __init__(self, **input_parameters):
        self.row_clusters = None
        self.col_clusters = None
        self.error = None
        self.nruns_completed = 0
        self.nruns_converged = 0
        super().__init__(**input_parameters)


class Coclustering(object):
    """
    Perform a co-clustering analysis for a two-dimensional array.

    :param Z: Data matrix for which to run the co-clustering analysis
    :type Z: numpy.ndarray or dask.array.Array
    :param nclusters_row: Number of row clusters.
    :type nclusters_row: int
    :param nclusters_col: Number of column clusters.
    :type nclusters_col: int
    :param conv_threshold: Convergence threshold for the objective function.
    :type conv_threshold: float, optional
    :param max_iterations: Maximum number of iterations.
    :type max_iterations: int, optional
    :param nruns: Number of differently-initialized runs.
    :type nruns: int, optional
    :param output_filename: Name of the JSON file where to write the results.
    :type output_filename: string, optional
    :param row_clusters_init: Initial row cluster assignment.
    :type row_clusters_init: numpy.ndarray or array_like, optional
    :param col_clusters_init: Initial column cluster assignment.
    :type col_clusters_init: numpy.ndarray or array_like, optional
    """
    def __init__(self,
                 Z,
                 nclusters_row,
                 nclusters_col,
                 conv_threshold=1.e-5,
                 max_iterations=1,
                 nruns=1,
                 output_filename='',
                 row_clusters_init=None,
                 col_clusters_init=None):
        # Input parameters -----------------
        self.nclusters_row = nclusters_row
        self.nclusters_col = nclusters_col
        self.conv_threshold = conv_threshold
        self.max_iterations = max_iterations
        self.nruns = nruns
        self.output_filename = output_filename
        self.row_clusters_init = row_clusters_init
        self.col_clusters_init = col_clusters_init
        # Input parameters end -------------

        # store input parameters in results object
        self.results = CoclusteringResults(**self.__dict__)

        assert Z.ndim == 2, 'Incorrect dimensionality for Z matrix'
        self.Z = Z

        if row_clusters_init is not None and col_clusters_init is not None:
            assert nruns == 1, 'Only nruns = 1 for given initial clusters'
            assert Z.shape == (len(row_clusters_init), len(col_clusters_init))

        self.client = None

    def run_with_dask(self, client=None, low_memory=True):
        """
        Run the co-clustering analysis using Dask.

        :param client: Dask client. If not specified, the default
            `LocalCluster` is employed.
        :type client: dask.distributed.Client, optional
        :param low_memory: If False, all runs are submitted to the Dask cluster
            (experimental feature, discouraged).
        :type low_memory: bool, optional
        :return: Co-clustering results.
        :type: cgc.coclustering.CoclusteringResults
        """
        self.client = client if client is not None else Client()

        if low_memory:
            self._dask_runs_memory()
        else:
            self._dask_runs_performance()

        self.results.write(filename=self.output_filename)
        return copy.copy(self.results)

    def run_with_threads(self, nthreads=1, low_memory=False):
        """
        Run the co-clustering using an algorithm based on Numpy plus threading
        (only suitable for local runs).

        :param nthreads: Number of threads employed to simultaneously run
            differently-initialized co-clustering analysis.
        :type nthreads: int, optional
        :param low_memory: Make use of a low-memory version of the algorithm
            with Numba JIT acceleration
        :type low_memory: bool, optional
        :return: Co-clustering results.
        :type: cgc.coclustering.CoclusteringResults
        """
        with ThreadPoolExecutor(max_workers=nthreads) as executor:
            futures = [
                executor.submit(coclustering_numpy.coclustering,
                                self.Z,
                                self.nclusters_row,
                                self.nclusters_col,
                                self.conv_threshold,
                                self.max_iterations,
                                low_memory,
                                row_clusters_init=self.row_clusters_init,
                                col_clusters_init=self.col_clusters_init)
                for _ in range(self.nruns)
            ]
            for future in concurrent.futures.as_completed(futures):
                logger.info(f'Retrieving run {self.results.nruns_completed}')
                converged, niters, row, col, e = future.result()
                self.results.nruns_completed += 1
                logger.info(f'Error = {e}')
                if converged:
                    logger.info(f'Run converged in {niters} iterations')
                    self.results.nruns_converged += 1
                else:
                    logger.warning(f'Run not converged in {niters} iterations')
                if self.results.error is None or e < self.results.error:
                    self.results.row_clusters = row
                    self.results.col_clusters = col
                    self.results.error = e
                    self.results.write(filename=self.output_filename)

        # write final results
        self.results.write(filename=self.output_filename)
        return copy.copy(self.results)

    def _dask_runs_memory(self):
        """ Memory efficient Dask implementation: sequential runs. """
        for r in range(self.nruns):
            logger.info(f'Run {self.results.nruns_completed}')
            converged, niters, row, col, e = coclustering_dask.coclustering(
                self.Z,
                self.nclusters_row,
                self.nclusters_col,
                self.conv_threshold,
                self.max_iterations,
                row_clusters_init=self.row_clusters_init,
                col_clusters_init=self.col_clusters_init)
            self.results.nruns_completed += 1
            logger.info(f'Error = {e}')
            if converged:
                logger.info(f'Run converged in {niters} iterations')
                self.results.nruns_converged += 1
            else:
                logger.warning(f'Run not converged in {niters} iterations')
            if self.results.error is None or e < self.results.error:
                self.results.row_clusters = row.compute()
                self.results.col_clusters = col.compute()
                self.results.error = e
                self.results.write(filename=self.output_filename)

    def _dask_runs_performance(self):
        """
        Faster but memory-intensive Dask implementation: all runs are
        simultaneously submitted to the scheduler (experimental, discouraged).
        """
        Z = self.client.scatter(self.Z)
        futures = [
            self.client.submit(coclustering_dask.coclustering,
                               Z,
                               self.nclusters_row,
                               self.nclusters_col,
                               self.conv_threshold,
                               self.max_iterations,
                               row_clusters_init=self.row_clusters_init,
                               col_clusters_init=self.col_clusters_init,
                               run_on_worker=True,
                               pure=False) for _ in range(self.nruns)
        ]
        for future, result in dask.distributed.as_completed(futures,
                                                            with_results=True):
            logger.info(f'Retrieving run {self.results.nruns_completed} ..')
            converged, niters, row, col, e = result
            self.results.nruns_completed += 1
            logger.info(f'Error = {e}')
            if converged:
                logger.info(f'Run converged in {niters} iterations')
                self.results.nruns_converged += 1
            else:
                logger.warning(f'Run not converged in {niters} iterations')
            if self.results.error is None or e < self.results.error:
                self.results.row_clusters = row.compute()
                self.results.col_clusters = col.compute()
                self.results.error = e
                self.results.write(filename=self.output_filename)
