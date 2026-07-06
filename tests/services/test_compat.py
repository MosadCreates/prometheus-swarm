from prometheus.utils.compat import check_python, check_os, check_all


class TestCompat:
    def test_check_python_ok(self):
        result = check_python()
        assert result["ok"] is True
        assert result["name"] == "Python"
        assert "3." in result["current"]

    def test_check_os_ok(self):
        result = check_os()
        assert result["ok"] is True
        assert result["name"] == "OS"

    def test_check_all_includes_expected(self):
        results = check_all()
        names = {r["name"] for r in results}
        assert "Python" in names
        assert "OS" in names
        assert "click" in names
        assert "rich" in names
        assert "shellingham" in names

    def test_check_all_all_pass(self):
        results = check_all()
        for r in results:
            assert r["ok"], f"{r['name']}: {r['current']} ({r['required']})"
