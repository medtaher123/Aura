from sqlalchemy import create_engine, text

import config

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        database_url = config.get_config().terrazard_database_url
        if not database_url:
            raise RuntimeError(
                "TerraZard database is not configured. Set TERRAZARD_DATABASE_URL."
            )
        _engine = create_engine(database_url)
    return _engine

def execute_read_query(query_str: str, params: dict) -> list[dict]:
    """Exécute une requête SELECT et retourne une liste de dictionnaires."""
    with _get_engine().connect() as conn:
        result = conn.execute(text(query_str), params)
        return [dict(row._mapping) for row in result]

def test_connection():
    try:
        with _get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        return False

if __name__ == "__main__":
    print(config.get_config().terrazard_database_url)
    print(test_connection())