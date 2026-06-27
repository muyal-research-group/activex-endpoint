import os

from axo_endpoint.service.runtime.scratch import (
    allocate_scratch_dir,
    cleanup_scratch_dir,
    sweep_orphaned_scratch_dirs,
)


def test_allocate_scratch_dir_creates_directory_and_returns_path(tmp_path):
    scratch_root = str(tmp_path / "scratch")
    path = allocate_scratch_dir(scratch_root, "job1")

    assert path == str(tmp_path / "scratch" / "job1")
    assert os.path.isdir(path)


def test_cleanup_scratch_dir_removes_it(tmp_path):
    scratch_root = str(tmp_path / "scratch")
    path = allocate_scratch_dir(scratch_root, "job1")

    cleanup_scratch_dir(path)

    assert not os.path.isdir(path)


def test_cleanup_scratch_dir_on_missing_path_does_not_raise(tmp_path):
    cleanup_scratch_dir(str(tmp_path / "never-existed"))  # must not raise


def test_sweep_orphaned_scratch_dirs_removes_only_inactive_directories(tmp_path):
    scratch_root = str(tmp_path / "scratch")
    active_path = allocate_scratch_dir(scratch_root, "active-job")
    orphaned_path = allocate_scratch_dir(scratch_root, "orphaned-job")

    removed = sweep_orphaned_scratch_dirs(scratch_root, active_job_ids={"active-job"})

    assert removed == ["orphaned-job"]
    assert os.path.isdir(active_path)
    assert not os.path.isdir(orphaned_path)


def test_sweep_orphaned_scratch_dirs_on_missing_root_returns_empty_list(tmp_path):
    removed = sweep_orphaned_scratch_dirs(str(tmp_path / "never-existed"), active_job_ids=set())
    assert removed == []
