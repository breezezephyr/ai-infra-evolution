import pytest
import window_toy


def test_equal_clipped_representations_do_not_prove_full_history_equivalence():
    row=window_toy.compare(list(range(1,17)),window=4,backtrack=2,layers=2,keep=6)
    assert row['single_window_covered']
    assert row['mask']==row['compact']==120
    assert row['full']==176 and not row['full_equal']


def test_same_suffix_is_sufficient_for_the_one_layer_toy():
    row=window_toy.compare(list(range(1,17)),4,2,1,6)
    assert row['full_equal'] and row['full']==50


@pytest.mark.parametrize('window',[2,4,8])
@pytest.mark.parametrize('layers',[1,2,3])
@pytest.mark.parametrize('backtrack',[0,1,3])
def test_dependency_coverage_is_sufficient_in_this_declared_toy(window,layers,backtrack):
    keep=layers*(window-1)+1+backtrack
    row=window_toy.compare(list(range(1,65)),window,backtrack,layers,keep)
    assert row['full_equal'] and row['dependency_covered']
    shorter=window_toy.compare(list(range(1,65)),window,backtrack,layers,keep-1)
    assert not shorter['full_equal']
    assert shorter['mask']==shorter['compact']


def test_backtracked_query_cannot_read_evicted_positions():
    row=window_toy.compare(list(range(1,17)),window=4,backtrack=6,layers=2,keep=3)
    assert row['status']=='query_evicted' and row['mask'] is None


def test_full_history_is_never_labelled_approximate_in_the_toy():
    row=window_toy.compare(list(range(1,17)),4,2,3,16)
    assert row['full_equal'] and row['start']==0


def test_invalid_geometry_is_explicit():
    for args in [([],4,0,2,6),([1,2],0,0,2,2),([1,2],2,0,0,2),([1,2],2,2,1,2),([1,2],2,0,1,0)]:
        with pytest.raises(ValueError):window_toy.compare(*args)
