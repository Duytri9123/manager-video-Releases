from unittest.mock import patch

from utils.edition import is_customer_edition


def test_customer_edition_only_in_separate_frozen_executable():
    with patch("sys.frozen", True, create=True):
        with patch("sys.executable", r"C:\Programs\DuyTrisCustomer.exe"):
            assert is_customer_edition()
        with patch("sys.executable", r"C:\Programs\DuyTrisDownloader.exe"):
            assert not is_customer_edition()


def test_source_run_is_not_customer_edition():
    with patch("sys.frozen", False, create=True):
        with patch("sys.executable", r"C:\Programs\DuyTrisCustomer.exe"):
            assert not is_customer_edition()
