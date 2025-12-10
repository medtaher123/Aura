# tests/conftest.py
import os
import pytest
import socket

def disable_network(monkeypatch):
    """Désactive le réseau."""
    def guard(*args, **kwargs):
        raise RuntimeError("Network access disabled during tests.")

    # Bloquer TCP
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: guard())

    # Bloquer requests
    try:
        import requests
        from requests.adapters import HTTPAdapter
        monkeypatch.setattr(
            HTTPAdapter, "send",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Network access disabled during tests."))
        )
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _control_network(request, monkeypatch):
    """
    Bloque le réseau pour tous les tests,
    SAUF pour test_regression.py (tests d'intégration).
    """
    try:
        # Nom du fichier test en cours
        test_file = request.node.fspath.basename

        # Autoriser réseau pour les tests de régression
        if test_file == "test_regression.py":
            print("Réseau autorisé pour test_regression.py")
            return

        # Bloquer le réseau pour les autres tests
        disable_network(monkeypatch)
    except Exception as e:
        # If network blocking fails, continue anyway (don't break setup)
        print(f"Warning: Could not disable network: {e}")

@pytest.fixture
def tmp_images_dir(tmp_path):
    """Répertoire temporaire pour fichiers/images générés."""
    cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)

