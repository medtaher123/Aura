
from sqlalchemy import create_engine, text

import config

engine = create_engine(config.get_config().terrazard_database_url)

#postgresql://admin_terrazard:inoP6!v&uoduoD@terrazard.c1aoyu6u0ilx.eu-west-3.rds.amazonaws.com:5432/hazard_archive

def execute_read_query(query_str: str, params: dict) -> list[dict]:
    """Exécute une requête SELECT et retourne une liste de dictionnaires."""
    with engine.connect() as conn:
        result = conn.execute(text(query_str), params)
        return [dict(row._mapping) for row in result]


def test_connection():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        return False


if __name__ == "__main__":
    print(config.get_config().terrazard_database_url)
    print(test_connection())