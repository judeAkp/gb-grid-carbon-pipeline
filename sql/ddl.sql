CREATE TABLE dbo.dim_fuel (
    fuel_key     TINYINT      NOT NULL PRIMARY KEY,
    fuel_name    NVARCHAR(20) NOT NULL UNIQUE,
    fuel_group   NVARCHAR(20) NOT NULL,          -- renewable / fossil / other
    is_renewable BIT          NOT NULL
);

CREATE TABLE dbo.dim_time (
    time_key         INT      NOT NULL PRIMARY KEY,   -- 1..1440, deterministic
    period_start_utc DATETIME2(0) NOT NULL UNIQUE,
    period_end_utc   DATETIME2(0) NOT NULL,
    local_date       DATE     NOT NULL,
    local_hour       TINYINT  NOT NULL,
    day_of_week      NVARCHAR(10) NOT NULL,
    is_weekend       BIT      NOT NULL,
    month_start      DATE     NOT NULL
);

CREATE TABLE dbo.fact_generation (
    time_key   INT     NOT NULL REFERENCES dbo.dim_time(time_key),
    fuel_key   TINYINT NOT NULL REFERENCES dbo.dim_fuel(fuel_key),
    percentage DECIMAL(5,2) NOT NULL,
    CONSTRAINT PK_fact_generation PRIMARY KEY (time_key, fuel_key),
    CONSTRAINT CK_fact_generation_pct CHECK (percentage BETWEEN 0 AND 100)
);

CREATE TABLE dbo.fact_intensity (
    time_key           INT     NOT NULL PRIMARY KEY REFERENCES dbo.dim_time(time_key),
    forecast_gco2_kwh  SMALLINT NOT NULL,
    actual_gco2_kwh    SMALLINT NOT NULL,
    intensity_index    NVARCHAR(10) NOT NULL
);

CREATE TABLE dbo.pipeline_runs (
    run_id          INT IDENTITY(1,1) PRIMARY KEY,
    pipeline_name   NVARCHAR(100) NOT NULL,
    month_start     DATE          NOT NULL,
    started_at_utc  DATETIME2(0)  NOT NULL,
    finished_at_utc DATETIME2(0)  NOT NULL,
    rows_generation INT           NOT NULL,
    rows_intensity  INT           NOT NULL,
    status          NVARCHAR(20)  NOT NULL,
    message         NVARCHAR(400) NULL
);