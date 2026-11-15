"""Project configuration. No secrets here - the API needs no key."""

API_BASE = "https://api.carbonintensity.org.uk"
PIPELINE_NAME = "gb_grid_carbon_intensity"

# SQL Server connection
DB_SERVER = "localhost"
DB_NAME = "DE_Learning"
DB_DRIVER = "ODBC Driver 18 for SQL Server"

# Classification decisions (documented in PROJECT.md)
RENEWABLE_FUELS = {"wind", "hydro", "solar", "biomass"}
FOSSIL_FUELS = {"gas", "coal"}

# Data quality thresholds
MIX_SUM_MIN = 98.0
MIX_SUM_MAX = 102.0
EXPECTED_FUELS = 9

# Local timezone for reporting attributes (data itself stays UTC)
LOCAL_TIMEZONE = "Europe/London"

def engine_url():
    return (
        f"mssql+pyodbc://{DB_SERVER}/{DB_NAME}"
        f"?driver={DB_DRIVER.replace(' ', '+')}"
        "&trusted_connection=yes&Encrypt=yes&TrustServerCertificate=yes"
    )
