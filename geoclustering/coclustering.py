import concurrent.futures
import dask.distributed
import logging

from concurrent.futures import ThreadPoolExecutor
from dask.distributed import Client

from . import coclustering_dask
from . import coclustering_numpy

logger = logging.getLogger(__name__)


class Coclustering(object):

    def __init__(self, Z, nclusters_row, nclusters_col, conv_threshold=1.e-5,
                 max_iterations=1, nruns=1, epsilon=1.e-8):
        """

        :param Z:
        :param nclusters_row:
        :param nclusters_col:
        :param conv_threshold:
        :param niterations:
        :param nruns:
        :param epsilon:
        """
        self.Z = Z
        self.nclusters_row = nclusters_row
        self.nclusters_col = nclusters_col
        self.conv_threshold = conv_threshold
        self.max_iterations = max_iterations
        self.nruns = nruns
        self.epsilon = epsilon

        self.client = None

        self.row_clusters = None
        self.col_clusters = None
        self.error = None

    def run_with_dask(self, client=None, low_memory=False):
        """

        :param client: Dask client
        :param low_memory: if true, use a memory-conservative algorithm
        :return:
        """
        self.client = client if client is not None else Client()

        if low_memory:
            self._dask_runs_memory()
        else:
            self._dask_runs_performance()

    def run_with_threads(self, nthreads=1):
        """

        :param nthreads:
        :return:
        """
        with ThreadPoolExecutor(max_workers=nthreads) as executor:
            futures = {
                executor.submit(coclustering_numpy.coclustering,
                                self.Z,
                                self.nclusters_row,
                                self.nclusters_col,
                                self.conv_threshold,
                                self.max_iterations,
                                self.epsilon):
                r for r in range(self.nruns)
            }
            row_min, col_min, e_min = None, None, 0.
            r = 0
            for future in concurrent.futures.as_completed(futures):
                logger.info(f'Waiting for run {r} ..')
                converged, niters, row, col, e = future.result()
                logger.info(f'Error = {e}')
                if converged:
                    logger.info(f'Run converged in {niters} iterations')
                else:
                    logger.warning(f'Run not converged in {niters} iterations')
                if e < e_min:
                    row_min, col_min, e_min = row, col, e
                r += 1
        self.row_clusters = row_min
        self.col_clusters = col_min
        self.error = e_min

    def run_serial(self):
        raise NotImplementedError

    def _dask_runs_memory(self):
        """ Memory efficient Dask implementation: serial loop over runs """
        row_min, col_min, e_min = None, None, 0.
        for r in range(self.nruns):
            logger.info(f'Run {r} ..')
            converged, niters, row, col, e = coclustering_dask.coclustering(
                self.Z,
                self.nclusters_row,
                self.nclusters_col,
                self.conv_threshold,
                self.max_iterations,
                self.epsilon
            )
            logger.info(f'Error = {e}')
            if converged:
                logger.info(f'Run converged in {niters} iterations')
            else:
                logger.warning(f'Run not converged in {niters} iterations')
            if e < e_min:
                row_min, col_min, e_min = row, col, e
        self.row_clusters = row_min.compute()
        self.col_clusters = col_min.compute()
        self.error = e_min

    def _dask_runs_performance(self):
        """
        Faster but memory-intensive Dask implementation: submit all runs to the
        scheduler
        """
        Z = self.client.scatter(self.Z)
        futures = [self.client.submit(coclustering_dask.coclustering,
                                      Z,
                                      self.nclusters_row,
                                      self.nclusters_col,
                                      self.conv_threshold,
                                      self.max_iterations,
                                      self.epsilon,
                                      run_on_worker=True,
                                      pure=False)
                   for r in range(self.nruns)]
        row_min, col_min, e_min = None, None, 0.
        r = 0
        for future, result in dask.distributed.as_completed(futures,
                                                            with_results=True,
                                                            raise_errors=False):
            logger.info(f'Waiting for run {r} ..')
            converged, niters, row, col, e = result
            e = e.compute()
            logger.info(f'Error = {e}')
            if converged:
                logger.info(f'Run converged in {niters} iterations')
            else:
                logger.warning(f'Run not converged in {niters} iterations')
            if e < e_min:
                row_min, col_min, e_min = row, col, e
            r += 1
        self.row_clusters = row_min.compute()
        self.col_clusters = col_min.compute()
        self.error = e_min

