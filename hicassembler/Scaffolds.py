import numpy as np
from scipy.sparse import csr_matrix
import logging
import time
import hicexplorer.HiCMatrix as HiCMatrix
from hicassembler.PathGraph import PathGraph
from hicassembler.HiCAssembler import HiCAssemblerException
from hicexplorer.reduceMatrix import reduce_matrix
from hicexplorer.iterativeCorrection import iterativeCorrection
from scipy.sparse import triu
from functools import wraps

logging.basicConfig()
log = logging.getLogger("Scaffolds")
log.setLevel(logging.DEBUG)


def logit(func):
    @wraps(func)
    def wrapper(*args, **kwds):
        log.info("Entering " + func.__name__)
        start_time = time.time()
        f_result = func(*args, **kwds)
        elapsed_time = time.time() - start_time
        log.info("Exiting {} after {} seconds".format(func.__name__, elapsed_time))
        return f_result
    return wrapper


class Scaffolds(object):
    """
    This class is a place holder to keep track of the iterative scaffolding.
    The underlying data structure is a special directed graph that does
    not allow more than two edges per node.

    The list of paths in the graph (in the same order) is paired with
    the rows in the HiC matrix.

    Example:

    Init a small HiC matrix
    >>> hic = get_test_matrix()
    >>> S = Scaffolds(hic)

    the list [('c-0', 0, 1, 1), ... ] has the format of the HiCMatrix attribute cut_intervals
    That has the format (chromosome name or contig name, start position, end position). Each
    HiC bin is determined by this parameters


    """
    def __init__(self, hic_matrix):
        """

        Parameters
        ----------
        cut_intervals

        Returns
        -------

        Examples
        -------
        >>> hic = get_test_matrix()
        >>> S = Scaffolds(hic)

        """
        # initialize the list of contigs as a graph with no edges
        self.hic = hic_matrix
        self.contig_G = PathGraph()
        self.path_id = {}  # maps nodes to paths
        self.split_contigs = None
        #self.id2contig_name = []

        # initialize the contigs directed graph
        self._init_path_graph()

    def _init_path_graph(self):
        """Uses the hic information for each row (cut_intervals)
        to initialize a path graph in which each node corresponds to
        a contig or a bin in a contig

        This method is called by the __init__ see example there

        Parameters
        ----------
        cut_intervals : the cut_intervals attribute of a HiCMatrix object

        Returns
        -------

        Example
        -------
        >>> cut_intervals = [('c-0', 0, 1, 1), ('c-1', 0, 1, 1), ('c-2', 0, 1, 1),
        ... ('c-4', 0, 1, 1), ('c-4', 0, 1, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)

        >>> S = Scaffolds(hic)
        >>> S.contig_G[0]
        [0]

        >>> S.contig_G[4]
        [3, 4]
        """

        contig_path = []
        prev_label = None
        length_array = []

        for idx, interval in enumerate(self.hic.cut_intervals):
            label, start, end, coverage = interval
            length = end - start

            attr = {'name': label,
                    'start': start,
                    'end': end,
                    'coverage': coverage,
                    'length': length}
            length_array.append(length)

            self.contig_G.add_node(idx, **attr)
            if prev_label != label:
                if len(contig_path) > 1:
                    self.contig_G.add_path(contig_path)
                contig_path = []
            contig_path.append(idx)
            prev_label = label

        if len(contig_path) > 1:
            self.contig_G.add_path(contig_path)

    def get_all_paths(self):
        """Returns all paths in the graph.
        This is similar to get connected components in networkx
        but in this case, the order of the returned  paths
        represents scaffolds of contigs

        >>> cut_intervals = [('c-0', 0, 1, 1), ('c-0', 1, 2, 1), ('c-0', 2, 3, 1),
        ... ('c-2', 0, 1, 1), ('c-2', 1, 2, 1), ('c-3', 0, 1, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> [x for x in S.get_all_paths()]
        [[0, 1, 2], [3, 4], [5]]
        """
        seen = set()
        for v in self.contig_G:
            if v not in seen:
                yield self.contig_G[v]
            seen.update(self.contig_G[v])

    def remove_bins_by_size(self, min_length):
        """
        Removes from HiC matrix all bins that are smaller than certain size
        Parameters
        ----------
        min_length

        Returns
        -------
        hic matrix

        Examples
        --------
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-2', 0, 10, 1), ('c-2', 20, 30, 1), ('c-3', 0, 10, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> hic = S.remove_bins_by_size(15)
        >>> [x for x in S.get_all_paths()]
        [[0, 1, 2], [3, 4]]

        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-2', 0, 10, 1), ('c-2', 20, 30, 1), ('c-3', 0, 10, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> hic = S.remove_bins_by_size(20)
        >>> [x for x in S.get_all_paths()]
        [[0, 1, 2]]

        >>> S.hic.matrix.todense()
        matrix([[ 2,  8,  5],
                [ 8,  8, 15],
                [ 5, 15,  0]])
        """
        to_keep = []
        for path in self.get_all_paths():
            length = (sum([self.contig_G.node[x]['length'] for x in path]))
            if length > min_length:
                to_keep.extend(path)

        if len(to_keep):
            new_matrix = self.hic.matrix[to_keep, :][:, to_keep]
            new_cut_intervals = [self.hic.cut_intervals[x] for x in to_keep]
            self.hic.update_matrix(new_matrix, new_cut_intervals)
            self.contig_G = PathGraph()
            self._init_path_graph()
        return self.hic

    def get_paths_length(self):
        for path in self.get_all_paths():
            yield (sum([self.contig_G.node[x]['length'] for x in path]))

    def compute_N50(self, min_length=200):
        """
        Computes the N50 based on the existing paths.

        Parameters
        ----------
        min_length : paths with a length smaller than this will be skiped

        Returns
        -------
        int : length of the N50 contig

        Examples
        --------
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-2', 0, 30, 1),
        ... ('c-3', 0, 10, 1), ('c-2', 20, 30, 1), ('c-3', 0, 10, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)

        The lengths for the paths in this matrix are:
        [20 30 10 10 10]

        The sorted cumulative sum is:
        [10, 20, 30, 50, 80]
        >>> S.compute_N50(min_length=2)
        20

        """
        length = np.sort(np.fromiter(self.get_paths_length(), int))
        if len(length) == 0:
            raise HiCAssemblerException("No paths. Can't compute N50")
        length = length[length > min_length]
        if len(length) == 0:
            raise HiCAssemblerException("No paths with length > {}. Can't compute N50".format(min_length))
        cumsum = np.cumsum(length)

        # find the index at which the cumsum length is half the total length
        half_length = float(cumsum[-1]) / 2
        for i in range(len(length)):
            if cumsum[i] >= half_length:
                break

        return length[i]

    @logit
    def merge_to_size(self, target_length=20000):
        """
        finds groups of bins/node that have a sum length of about the `target_length` size.
        The algorithm proceeds from the flanks of a path to the inside. If a bin/node
        is too small it is skipped.

        Parameters
        ----------
        target_length : in bp

        Returns
        -------

        Examples
        --------
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-0', 30, 40, 1), ('c-0', 40, 50, 1), ('c-0', 50, 60, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> list(S.get_all_paths())
        [[0, 1, 2, 3, 4, 5]]
        >>> hic = S.merge_to_size(target_length=20)
        >>> S.hic.matrix.todense()
        matrix([[ 11.26259299,  21.9378206 ,  17.42795074],
                [ 21.9378206 ,   6.86756935,  21.82307214],
                [ 17.42795074,  21.82307214,  11.37726956]])
        >>> S.hic.cut_intervals
        [('c-0', 0, 20, 10.5), ('c-0', 20, 40, 20.5), ('c-0', 40, 60, 30.5)]
        >>> list(S.get_all_paths())
        [[0, 1, 2]]
        """
        log.info("merge_to_size. flank_length: {}".format(target_length))

        # flattened list of merged_paths  e.g [[1,2],[3,4],[5,6],[7,8]].
        # This is in contrast to a list containing flanks_of_path that may
        # look like [ [[1,2],[3,4]], [[5,6]] ]
        paths_flatten = []

        # list to keep the id of the new flanks_of_path after they
        # are merged. For example, for a flanks_of_path list e.g. [[0,1], [2,3]]]
        # after merging (that is matrix merging of the respective bins e.g 0 and 1)
        # the [0,1] becomes bin [0] and [2,3] becomes bin 1. Thus, merged_paths_id_map
        # has the value [[0,1]]. Further merged paths are appended as new lists
        # eg [[0,1], [2,3] .. etc. ]
        merged_paths_id_map = []
        i = 0
        for path in self.get_all_paths():
            flanks_of_path = self.get_flanks(path, target_length, 100)
            merged_paths_id_map.append(range(i, len(flanks_of_path)+i))
            i += len(flanks_of_path)
            paths_flatten.extend(flanks_of_path)

        if len(paths_flatten) == 0:
            log.warn("[{}] Nothing to reduce.".format(inspect.stack()[0][3]))
            return None
        # define new intervals based on the paths that will be merged
        new_cut_intervals = []
        for sub_path in paths_flatten:
            first_node = sub_path[0]
            last_node = sub_path[-1]
            name = self.contig_G.node[first_node]['name']
            start = self.contig_G.node[first_node]['start']
            end = self.contig_G.node[last_node]['end']
            if end < start:
                import ipdb; ipdb.set_trace()
            assert start < end
            coverage = float(self.contig_G.node[first_node]['coverage'] +
                             self.contig_G.node[last_node]['end']) / 2

            new_cut_intervals.append((name, start, end, coverage))

        reduce_paths = paths_flatten[:]

        if len(reduce_paths) < 2:
            log.info("Reduce paths to small {}. Returning".format(len(reduce_paths)))
            return None, None
        reduced_matrix = reduce_matrix(self.hic.matrix, reduce_paths, diagonal=True)

        # correct reduced_matrix
        start_time = time.time()
        corrected_matrix = iterativeCorrection(reduced_matrix, M=1000, verbose=True)[0]
        elapsed_time = time.time() - start_time
        log.debug("time iterative_correction: {:.5f}".format(elapsed_time))

        # update matrix
        self.hic = HiCMatrix.hiCMatrix()
        self.hic.setMatrix(corrected_matrix, new_cut_intervals)

        # update paths
        self.contig_G = PathGraph()
        self._init_path_graph()

        # TODO: remove debug line
        self.hic.save("data/merged_bins_corrected.h5")
        return self.hic

    def get_flanks(self, path, flank_length, recursive_repetitions, counter=0):
        """
        Takes a path and returns the flanking regions plus the inside. This is a
        recursive function and will split the inside as many times as possible,
        stopping when 'recursive_repetitions' have been reached

        Parameters
        ----------
        path : list of ids
        flank_length : length in bp of the flank lengths that want to be kept
        contig_len : list with the lengths of the contig/bis in the path. The
                     index in the list are considered to be the length for bin
                     id.
        recursive_repetitions : If recursive, then the flanks of the inside
                    part of the path (the interior part) are also returned

        counter : internal counter to keep track of recursive repetitions

        Returns
        -------

        Examples
        --------

        The flank length is set to 2000, thus, groups of two should be
        selected
        # make one matrix whith only one split contig c-0 whose
        # bins have all 10 bp
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-0', 30, 40, 1), ('c-0', 40, 50, 1), ('c-0', 50, 60, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> flank_length = 20
        >>> S.get_flanks(S.contig_G[0], flank_length, 30)
        [[0, 1], [2, 3], [4, 5]]

        # 5 bins, one internal is smaller than 20*75 (flank_length * tolerance) is skipped
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-0', 30, 40, 1), ('c-0', 40, 50, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> flank_length = 20
        >>> S.get_flanks(S.contig_G[0], flank_length, 30)
        [[0, 1], [3, 4]]

        Get the flanks, and do not recursively iterate
        # 5 bins, one internal is smaller than 20*75 (flank_length * tolerance) is skipped
        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-0', 30, 40, 1), ('c-0', 40, 50, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> flank_length = 10
        >>> S.get_flanks(S.contig_G[0], flank_length, 1)
        [[0], [4]]

        """
        counter += 1
        if counter > recursive_repetitions:
            return []

        tolerance_max = flank_length * 1.25
        tolerance_min = flank_length * 0.75
        path_length = dict([(x, self.contig_G.node[x]['length']) for x in path])
        path_length_sum = sum(path_length.values())
        flanks = []

        def _get_path_flank(_path):
            """
            returns the first k ids in a path such that the sum of the lengths for _path[k] is
            between tolerance_min and tolerance_max

            Parameters
            ----------
            _path : list of ids

            Returns
            -------
            _path[0:k] such that the length of the bins in _path[0:k] is between tolerance_min and tolerance_max
            """
            flank = []
            for n in _path:
                flank_sum = sum(path_length[x] for n in flank)
                if flank_sum > tolerance_max:
                    break
                elif tolerance_min <= flank_sum <= tolerance_max:
                    break
                flank.append(n)
            return flank

        if len(path) == 1:
            if path_length[path[0]] > tolerance_min or counter == 1:
                flanks = [path]
        else:
            if path_length_sum < 2*flank_length*0.75:
                if counter == 1:
                    # if the total path length is shorter than twice the flank_length *.75
                    # then split the path into two
                    log.debug("path {} is being divided into two, although is quite small {}".format(path, path_length_sum))
                    path_half = len(path)/2
                    left_flank = path[0:path_half]
                    right_flank = path[path_half:]
                    flanks.extend([left_flank, right_flank])
                else:
                    flanks.extend([path])
                    log.debug("is small and has no flanks".format(path, path_length_sum))
            else:
                left_flank = _get_path_flank(path)
                right_flank = _get_path_flank(path[::-1])[::-1]

                # check if the flanks overlap
                over = set(left_flank).intersection(right_flank)
                if len(over):
                    # remove overlap
                    left_flank = [x for x in left_flank if x not in over]

                if len(left_flank) == 0 or len(right_flank) == 0:
                    path_half = len(path)/2
                    left_flank = path[0:path_half]
                    right_flank = path[path_half:]

                interior = [x for x in path if x not in left_flank + right_flank]
                if len(interior):
                    interior = self.get_flanks(interior, flank_length, recursive_repetitions, counter=counter)
                if len(left_flank):
                    flanks.append(left_flank)
                if len(interior):
                    flanks.extend(interior)
                if len(right_flank):
                    flanks.append(right_flank)

            try:
                if len(left_flank) == 0 or len(right_flank) == 0:
                    import pdb;pdb.set_trace()
            except:
                pass

        return flanks

    def get_stats_per_distance(self):
        """
        takes the information from all bins that are split
        or merged and returns two values and two vectors. The
        values are the average length used and the sd.
        The vectors are: one containing the number of contacts found for such
        distance and the third one containing the normalized
        contact counts for different distances.
        The distances are 'bin' distance. Thus,
        if two bins are next to each other, they are at distance 1

        Returns
        -------
        mean bin length, std bin length, dict containing as key the bin distance
        and as values a dict with mean, median, max, min and len

        Examples
        --------

        >>> cut_intervals = [('c-0', 0, 10, 1), ('c-0', 10, 20, 1), ('c-0', 20, 30, 1),
        ... ('c-0', 30, 40, 1), ('c-0', 40, 50, 1), ('c-0', 50, 60, 1)]
        >>> hic = get_test_matrix(cut_intervals=cut_intervals)
        >>> S = Scaffolds(hic)
        >>> mean, sd, stats = S.get_stats_per_distance()
        >>> stats[2]['mean']
        4.25

        """
        log.info("Computing stats per distance")

        # get all paths (connected components) longer than 1
        if len(self.contig_G.path) == 0:
            raise HiCAssemblerException("Print no paths found\n")

        # use all paths to estimate distances
        dist_dict = dict()
        path_length = []
        for count, path in enumerate(self.contig_G.path.values()):
            if count > 200:
                # otherwise too many computations will be made
                # but 200 cases are enough to get
                # an idea of the distribution of values
                break
            for n in path:
                path_length.append(self.contig_G.node[n]['length'])

            # take upper triangle of matrix containing selected path
            sub_m = triu(self.hic.matrix[path, :][:, path], k=1, format='coo')
            # find counts that are one bin apart, two bins apart etc.
            dist_list = sub_m.col - sub_m.row
            # tabulate all values that correspond
            # to distances
            for distance in np.unique(dist_list):
                if distance not in dist_dict:
                    dist_dict[distance] = sub_m.data[dist_list == distance]
                else:
                    dist_dict[distance] = np.hstack([dist_dict[distance],
                                                     sub_m.data[dist_list == distance]])

        # get mean and sd of the bin lengths
        mean_path_length = np.mean(path_length)
        sd_path_length = np.std(path_length)
        log.info("Mean path length: {} sd{}".format(mean_path_length, sd_path_length))

        # consolidate data:
        consolidated_dist_value = dict()
        for k, v in dist_dict.iteritems():
            consolidated_dist_value[k] = {'mean': np.mean(v),
                                          'median': np.median(v),
                                          'max': np.max(v),
                                          'min': np.min(v),
                                          'len': len(v)}
            if len(v) < 10:
                log.warn('stats for distance {} contain only {} samples'.format(k, len(v)))
        return mean_path_length, sd_path_length, consolidated_dist_value

    @logit
    def get_nearest_neighbors(self, confidence_score):
        matrix = self.hic.matrix.copy()

        matrix.data[matrix.data <= confidence_score] = 0
        matrix.eliminate_zeros()
        matrix = triu(matrix, k=1, format='coo')

        flanks = []
        singletons = []
        for path in self.get_all_paths():
            if len(path) == 1:
                singletons.extend(path)
            else:
                flanks.extend([path[0], path[-1]])

        import networkx as nx

        G=nx.Graph()
        nodes = flanks + singletons
        for index, value in enumerate(matrix.data):
            row_id = matrix.row[index]
            col_id = matrix.col[index]
            if row_id in nodes and col_id in nodes:
                G.add_edge(row_id, col_id, weight=value)

        seen = set()
        for node in G:
            if G.degree(node) == 1 and node in flanks and node not in seen:
                try:
                    self.contig_G.add_edge(node, G[node].keys()[0])
                except:
                    pass
                seen.update([node, G[node].keys()[0]])
            elif G.degree(node) == 2 and node in singletons and node not in seen:
                self.contig_G.add_edge(node, G[node].keys()[0])
                seen.update([node, G[node].keys()[0]])
                self.contig_G.add_edge(node, G[node].keys()[1])
                seen.add(G[node].keys()[1])

            else:
                log.info("Node {} is a hub with degree {}".format(node, G.degree(node)))

        import ipdb;ipdb.set_trace()

    @logit
    def get_nearest_neighbors_2(self, confidence_score):
        """

        Parameters
        ----------
        confidence_score : threshold to prune the matrix. Any value
        below this score is removed.

        Returns
        -------

        """
        """ Thu, 23 May 2013 16:14:51
        The idea is to take the matrix and order it
        such that neighbors are placed next to each other.

        The algorithm is as follows:

        1. identify the cell with  highest number of shared pairs and
        save the pair of rows that corresponds to that cell.
        2. remove that number from the matrix.
        3. Quit if all nodes already have 'min_neigh' neighbors,
           otherwise repeat.

        In theory, if everything is consistent, at the end of
        the for loop each node should have *only* two
        neighbors. This is rarely the case and some of the nodes
        end up with more than two neighbors. However, a large
        fraction of the nodes only have two neighbors and they
        can be chained one after the other to form a super
        contig.

        Parameters:
        ----------
        min_neigh: minimun number of neighbors to consider.
                   If set to two, the function exists when
                   all contigs have at least two neighbors.
        """

        # consider only the upper triangle of the
        # matrix and convert it to COO for quick
        # operations
        try:
            ma = triu(self.cmatrix, k=1, format='coo')
        except:
            import pdb; pdb.set_trace()
        order_index = np.argsort(ma.data)[::-1]
        # neighbors dictionary
        # holds, for each node the list of neighbors
        # using a sparse matrix is much faster
        # than creating a network and populating it
        net = lil_matrix(ma.shape, dtype='float64')

        # initialize neighbors dict
        neighbors = {}
        for index in range(ma.shape[0]):
            neighbors[index] = (0, 0)

        counter = 0
        for index in order_index:
            counter += 1
            if counter % 10000 == 0:
                print "[{}] {}".format(inspect.stack()[0][3], counter)
            row = ma.row[index]
            col = ma.col[index]
            if col == row:
                continue
            if ma.data[index] < threshold:
                break

            # do not add edges if the number of contacts
            # in the uncorrected matrix is below
            if self.matrix[row, col] < 10:
                continue


            # if a contig (or path when they are merged)
            # has already two neighbors and the second
            # neighbor has a number of contacts equal to max_int
            # it means that this node is already connected to
            # two other nodes that already have been decided
            # and further connections to such nodes are skipped.
            # It is only necesary to check if the last neighbor
            # added to the node is equal to max_int because
            # the first node, must have also been max_int.
            if neighbors[row][1] == 2 and neighbors[row][0] == max_int:
                continue
            if neighbors[col][1] == 2 and neighbors[col][0] == max_int:
                continue

            # add an edge if the number of neighbors
            # is below min_neigh:
            if neighbors[row][1] < min_neigh and \
                    neighbors[col][1] < min_neigh:
                neighbors[row] = (ma.data[index], neighbors[row][1]+1)
                neighbors[col] = (ma.data[index], neighbors[col][1]+1)
                net[row, col] = ma.data[index]

            # add further edges if a high value count exist
            # that is higher than the expected power law decay
            elif ma.data[index] > neighbors[row][0]*POWER_LAW_DECAY and \
                    ma.data[index] > neighbors[col][0]*POWER_LAW_DECAY:
                if neighbors[row][1] < min_neigh:
                    neighbors[row] = (ma.data[index], neighbors[row][1]+1)

                if neighbors[col][1] < min_neigh:
                    neighbors[col] = (ma.data[index], neighbors[col][1]+1)
                net[row, col] = ma.data[index]

        G = nx.from_scipy_sparse_matrix(net, create_using=nx.Graph())
        if trans:
            # remap ids
            mapping = dict([(x,paths[x][0]) for x in range(len(paths))])
            G = nx.relabel_nodes(G, mapping)

        # remove all edges not connected to flanks
        # the idea is that if a path already exist
        # no edges should point to it unless
        # is they are the flanks
        """
        if self.iteration==2:
            import pdb;pdb.set_trace()
        if self.merged_paths:
            flanks = set(HiCAssembler.flatten_list(
                    [[x[0],x[-1]] for x in self.merged_paths]))
            for edge in G.edges():
                if len(flanks.intersection(edge)) == 0:
                    G.remove_edge(*edge)
        """
        return G

    #########

    def remove_paths(self, ids_to_remove):
        """
        Removes a path from the self.path list
        using the given ids_to_remove
        Parameters
        ----------
        ids_to_remove : List of ids to be removed. Eg. [1, 5, 20]

        Returns
        -------
        None
        """
        paths = self.get_all_paths()
        # translate path indices in mask_list back to contig ids
        # and merge into one list using sublist trick
        paths_to_remove = [paths[x] for x in ids_to_remove]
        contig_list = [item for sublist in paths_to_remove for item in sublist]

        self.contig_G.remove_nodes_from(contig_list)
        # reset the paths
        self.paths = None

    def has_edge(self, u, v):
        return self.contig_G.has_edge(u, v) or self.contig_G.has_edge(v, u)

    def check_edge(self, u, v):
        # check if the edge already exists
        if self.has_edge(u, v):
            message = "Edge between {} and {} already exists".format(u, v)
            raise HiCAssemblerException(message)

        # check if the node has less than 2 edges
        for node in [u, v]:
            if self.contig_G.degree(node) == 2:
                message = "Edge between {} and {} not possible,  contig {} " \
                          "is not a flaking node ({}, {}). ".format(u, v, node,
                                                                    self.contig_G.predecessors(node),
                                                                    self.contig_G.successors(node))
                raise HiCAssemblerException(message)

        # check if u an v are the two extremes of a path,
        # joining them will create a loop
        if self.contig_G.degree(u) == 1 and self.contig_G.degree(v) == 1:
            if v in self.contig_G[u]:
                message = "The edges {}, {} form a closed loop.".format(u, v)
                raise HiCAssemblerException(message)

    def get_neighbors(self, u):
        """
        Give a node u, it returns the
        successor and predecessor nodes

        Parameters
        ----------
        u : Node

        Returns
        -------
        predecessors and sucessors

        """
        return self.contig_G.predecessors(u) + self.contig_G.successors(u)

    def save_network(self, file_name):
        nx.write_gml(self.contig_G, file_name)


def get_test_matrix(cut_intervals=None):
    hic = HiCMatrix.hiCMatrix()
    hic.nan_bins = []
    matrix = np.array([
    [ 1,  8,  5, 3, 0, 8],
    [ 0,  4, 15, 5, 1, 7],
    [ 0,  0,  0, 7, 2, 8],
    [ 0,  0,  0, 0, 1, 5],
    [ 0,  0,  0, 0, 0, 6],
    [ 0,  0,  0, 0, 0, 0]])

    # make matrix symmetric
    matrix = csr_matrix(matrix + matrix.T)

    if not cut_intervals:
        cut_intervals = [('c-0', 0, 1, 1), ('c-1', 0, 1, 1), ('c-2', 0, 1, 1), ('c-4', 0, 1, 1), ('c-4', 0, 1, 1)]
    hic.matrix = csr_matrix(matrix[0:len(cut_intervals), 0:len(cut_intervals)])
    hic.setMatrix(hic.matrix, cut_intervals)
    return hic
