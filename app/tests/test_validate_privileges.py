"""_privileges write validator."""

import pytest
import utils.data_access as da


class TestValidatePrivileges:
    def test_valid_admin_entry(self):
        result = da.validate_privileges([{"level": "admin"}])
        assert result == [{"level": "admin"}]

    def test_valid_matrikel_admin_entry(self):
        """matrikel_admin is a live, unscoped role like admin."""
        result = da.validate_privileges([{"level": "matrikel_admin"}])
        assert result == [{"level": "matrikel_admin"}]

    def test_valid_manager_entry(self):
        result = da.validate_privileges([{"level": "manager", "genebank": 1}])
        assert result == [{"level": "manager", "genebank": 1}]

    def test_valid_viewer_entry(self):
        result = da.validate_privileges([{"level": "viewer", "genebank": 2}])
        assert result == [{"level": "viewer", "genebank": 2}]

    def test_valid_owner_entry_uses_numeric_herd_id(self):
        """owner.herd stores the numeric Herd.id, never a string."""
        result = da.validate_privileges([{"level": "owner", "herd": 42}])
        assert result == [{"level": "owner", "herd": 42}]

    def test_valid_mixed_list(self):
        result = da.validate_privileges(
            [
                {"level": "admin"},
                {"level": "manager", "genebank": 1},
                {"level": "owner", "herd": 42},
            ]
        )
        assert len(result) == 3

    def test_reject_unknown_level(self):
        with pytest.raises(ValueError, match="Okänd nivå"):
            da.validate_privileges([{"level": "root"}])

    def test_reject_manager_without_genebank(self):
        with pytest.raises(ValueError, match="kräver 'genebank'"):
            da.validate_privileges([{"level": "manager"}])

    def test_reject_viewer_without_genebank(self):
        with pytest.raises(ValueError, match="kräver 'genebank'"):
            da.validate_privileges([{"level": "viewer"}])

    def test_reject_owner_without_herd(self):
        with pytest.raises(ValueError, match="kräver 'herd'"):
            da.validate_privileges([{"level": "owner"}])

    def test_reject_admin_with_extra_key(self):
        with pytest.raises(ValueError, match="får inte ha extra fält"):
            da.validate_privileges([{"level": "admin", "herd": 42}])

    def test_reject_matrikel_admin_with_extra_key(self):
        with pytest.raises(ValueError, match="får inte ha extra fält"):
            da.validate_privileges([{"level": "matrikel_admin", "genebank": 1}])

    def test_reject_string_int_genebank(self):
        with pytest.raises(ValueError, match="måste vara heltal"):
            da.validate_privileges([{"level": "manager", "genebank": "1"}])

    def test_reject_string_int_herd(self):
        """String herd names were once wrongly accepted; the data path
        only supports int Herd.id."""
        with pytest.raises(ValueError, match="måste vara heltal"):
            da.validate_privileges([{"level": "owner", "herd": "G12"}])

    def test_reject_bool_disguised_as_int(self):
        """bool is a subclass of int in Python — must be rejected explicitly."""
        with pytest.raises(ValueError, match="måste vara heltal"):
            da.validate_privileges([{"level": "manager", "genebank": True}])

    def test_reject_non_list_input(self):
        with pytest.raises(ValueError, match="måste vara en lista"):
            da.validate_privileges({"level": "admin"})

    def test_reject_non_dict_entry(self):
        with pytest.raises(ValueError, match="måste vara ett objekt"):
            da.validate_privileges(["admin"])

    def test_reject_missing_level(self):
        with pytest.raises(ValueError, match="saknar 'level'"):
            da.validate_privileges([{"genebank": 1}])

    def test_string_values_are_stripped(self):
        result = da.validate_privileges([{"level": "  admin  "}])
        assert result == [{"level": "admin"}]

    def test_empty_list_valid(self):
        assert da.validate_privileges([]) == []
