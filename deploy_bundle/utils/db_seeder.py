"""
Database Seeder: Automated Chinook / E-Commerce SQLite database seeder.
Ensures an instant, out-of-the-box working database with training DDLs and examples.
"""
import logging
import os
import sqlite3
import urllib.request
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.vanna_client import VannaTextToSQLEngine

logger = logging.getLogger("TextToSQL.Seeder")

CHINOOK_URL = "https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite"


def seed_database(target_path: Optional[str] = None, seed_vanna: bool = True) -> str:
    """
    Ensure a fully populated SQLite database is ready at target_path.
    Attempts to download the official Chinook database; if offline or unavailable,
    synthesizes a rich enterprise E-Commerce & Chinook database locally.
    """
    config = get_config()
    db_path = Path(target_path or config.db.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # If database already exists and is non-empty (>10KB), skip re-download
    if db_path.exists() and db_path.stat().st_size > 10000:
        logger.info(f"Existing database detected at {db_path} ({db_path.stat().st_size} bytes).")
        if seed_vanna:
            _train_vector_store(str(db_path))
        return str(db_path)

    logger.info(f"Provisioning database at {db_path}...")

    # Attempt download
    downloaded = False
    try:
        logger.info(f"Attempting download from {CHINOOK_URL}...")
        req = urllib.request.Request(
            CHINOOK_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=10) as response, open(db_path, "wb") as out_file:
            out_file.write(response.read())
        if db_path.exists() and db_path.stat().st_size > 50000:
            downloaded = True
            logger.info("Official Chinook database downloaded successfully.")
    except Exception as err:
        logger.warning(f"Could not download Chinook database ({err}). Generating synthetic enterprise database...")

    if not downloaded:
        _create_synthetic_enterprise_db(str(db_path))

    if seed_vanna:
        _train_vector_store(str(db_path))

    return str(db_path)


def _create_synthetic_enterprise_db(db_path: str):
    """Generate a rich, offline Chinook-compatible and E-commerce database."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Chinook Core Tables
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS Artist (
        ArtistId INTEGER PRIMARY KEY AUTOINCREMENT,
        Name NVARCHAR(120)
    );

    CREATE TABLE IF NOT EXISTS Genre (
        GenreId INTEGER PRIMARY KEY AUTOINCREMENT,
        Name NVARCHAR(120)
    );

    CREATE TABLE IF NOT EXISTS MediaType (
        MediaTypeId INTEGER PRIMARY KEY AUTOINCREMENT,
        Name NVARCHAR(120)
    );

    CREATE TABLE IF NOT EXISTS Album (
        AlbumId INTEGER PRIMARY KEY AUTOINCREMENT,
        Title NVARCHAR(160) NOT NULL,
        ArtistId INTEGER NOT NULL,
        FOREIGN KEY (ArtistId) REFERENCES Artist (ArtistId)
    );

    CREATE TABLE IF NOT EXISTS Track (
        TrackId INTEGER PRIMARY KEY AUTOINCREMENT,
        Name NVARCHAR(200) NOT NULL,
        AlbumId INTEGER,
        MediaTypeId INTEGER NOT NULL,
        GenreId INTEGER,
        Composer NVARCHAR(220),
        Milliseconds INTEGER NOT NULL,
        Bytes INTEGER,
        UnitPrice NUMERIC(10,2) NOT NULL,
        FOREIGN KEY (AlbumId) REFERENCES Album (AlbumId),
        FOREIGN KEY (GenreId) REFERENCES Genre (GenreId),
        FOREIGN KEY (MediaTypeId) REFERENCES MediaType (MediaTypeId)
    );

    CREATE TABLE IF NOT EXISTS Customer (
        CustomerId INTEGER PRIMARY KEY AUTOINCREMENT,
        FirstName NVARCHAR(40) NOT NULL,
        LastName NVARCHAR(20) NOT NULL,
        Company NVARCHAR(80),
        Address NVARCHAR(70),
        City NVARCHAR(40),
        State NVARCHAR(40),
        Country NVARCHAR(40),
        PostalCode NVARCHAR(10),
        Phone NVARCHAR(24),
        Fax NVARCHAR(24),
        Email NVARCHAR(60) NOT NULL,
        SupportRepId INTEGER
    );

    CREATE TABLE IF NOT EXISTS Invoice (
        InvoiceId INTEGER PRIMARY KEY AUTOINCREMENT,
        CustomerId INTEGER NOT NULL,
        InvoiceDate DATETIME NOT NULL,
        BillingAddress NVARCHAR(70),
        BillingCity NVARCHAR(40),
        BillingState NVARCHAR(40),
        BillingCountry NVARCHAR(40),
        BillingPostalCode NVARCHAR(10),
        Total NUMERIC(10,2) NOT NULL,
        FOREIGN KEY (CustomerId) REFERENCES Customer (CustomerId)
    );

    CREATE TABLE IF NOT EXISTS InvoiceLine (
        InvoiceLineId INTEGER PRIMARY KEY AUTOINCREMENT,
        InvoiceId INTEGER NOT NULL,
        TrackId INTEGER NOT NULL,
        UnitPrice NUMERIC(10,2) NOT NULL,
        Quantity INTEGER NOT NULL,
        FOREIGN KEY (InvoiceId) REFERENCES Invoice (InvoiceId),
        FOREIGN KEY (TrackId) REFERENCES Track (TrackId)
    );

    -- 2. E-Commerce Extension Tables
    CREATE TABLE IF NOT EXISTS Products (
        ProductId INTEGER PRIMARY KEY AUTOINCREMENT,
        Name NVARCHAR(100) NOT NULL,
        Category NVARCHAR(50) NOT NULL,
        Price NUMERIC(10,2) NOT NULL,
        StockQuantity INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS Orders (
        OrderId INTEGER PRIMARY KEY AUTOINCREMENT,
        CustomerId INTEGER NOT NULL,
        OrderDate DATETIME NOT NULL,
        OrderStatus NVARCHAR(30) NOT NULL,
        TotalAmount NUMERIC(10,2) NOT NULL,
        FOREIGN KEY (CustomerId) REFERENCES Customer (CustomerId)
    );
    """)

    # Populate Sample Data
    cur.executescript("""
    INSERT INTO Artist (Name) VALUES 
        ('AC/DC'), ('Accept'), ('Aerosmith'), ('Alanis Morissette'), ('Alice In Chains'),
        ('Led Zeppelin'), ('Queen'), ('Pink Floyd'), ('Miles Davis'), ('U2');

    INSERT INTO Genre (Name) VALUES 
        ('Rock'), ('Jazz'), ('Metal'), ('Alternative & Punk'), ('Blues'), ('Latin'), ('Classical');

    INSERT INTO MediaType (Name) VALUES 
        ('MPEG audio file'), ('Protected AAC audio file'), ('Protected MPEG-4 video file'), ('Purchased AAC audio file');

    INSERT INTO Album (Title, ArtistId) VALUES 
        ('For Those About To Rock We Salute You', 1),
        ('Let There Be Rock', 1),
        ('Balls to the Wall', 2),
        ('Restless and Wild', 2),
        ('Jagged Little Pill', 4),
        ('A Night at the Opera', 7),
        ('The Dark Side of the Moon', 8),
        ('Kind of Blue', 9);

    INSERT INTO Track (Name, AlbumId, MediaTypeId, GenreId, Composer, Milliseconds, Bytes, UnitPrice) VALUES 
        ('For Those About To Rock (We Salute You)', 1, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 343719, 11170334, 0.99),
        ('Put The Finger On You', 1, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 205662, 6713451, 0.99),
        ('Let''s Get It Up', 1, 1, 1, 'Angus Young, Malcolm Young, Brian Johnson', 233926, 7636944, 0.99),
        ('Bohemian Rhapsody', 6, 1, 1, 'Freddie Mercury', 354320, 11543820, 1.29),
        ('Love of My Life', 6, 1, 1, 'Freddie Mercury', 218000, 7120000, 0.99),
        ('Money', 7, 1, 1, 'Roger Waters', 382000, 12450000, 1.29),
        ('So What', 8, 1, 2, 'Miles Davis', 562000, 18230000, 1.49);

    INSERT INTO Customer (FirstName, LastName, Company, Address, City, State, Country, PostalCode, Phone, Email) VALUES 
        ('Luís', 'Gonçalves', 'Embraer - Empresa Brasileira de Aeronáutica S.A.', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', '+55 (12) 3923-5555', 'luisg@embraer.com.br'),
        ('Leonie', 'Köhler', NULL, 'Theodor-Heuss-Straße 34', 'Stuttgart', NULL, 'Germany', '70174', '+49 0711 2842222', 'leonekohler@surfeu.de'),
        ('François', 'Tremblay', NULL, '1498 rue Bélanger', 'Montréal', 'QC', 'Canada', 'H2G 1A7', '+1 (514) 721-4712', 'ftremblay@gmail.com'),
        ('Bjørn', 'Hansen', NULL, 'Ullevålsveien 14', 'Oslo', NULL, 'Norway', '0171', '+47 22 12 13 14', 'bjorn.hansen@yahoo.no'),
        ('Helena', 'Holý', NULL, 'Rilkeho 3174/6', 'Prague', NULL, 'Czech Republic', '14300', '+420 2 4172 5555', 'hholy@gmail.com'),
        ('Astrid', 'Gruber', NULL, 'Rotenturmstraße 4, 1010 Innere Stadt', 'Vienna', NULL, 'Austria', '1010', '+43 01 5134559', 'astrid.gruber@apple.at'),
        ('Dan', 'Miller', NULL, '541 Del Medio Avenue', 'Mountain View', 'CA', 'USA', '94040-111', '+1 (650) 644-3358', 'dmiller@comcast.net'),
        ('Kara', 'Nielsen', NULL, 'Frauenstraße 19', 'Berlin', NULL, 'Germany', '10623', '+49 030 33452', 'kara.nielsen@jubii.dk'),
        ('Eduardo', 'Martins', 'Woodstock Discos', 'Rua Dr. Falcão Filho, 155', 'São Paulo', 'SP', 'Brazil', '01007-010', '+55 (11) 3033-5446', 'eduardo@woodstock.com.br');

    INSERT INTO Invoice (CustomerId, InvoiceDate, BillingAddress, BillingCity, BillingState, BillingCountry, BillingPostalCode, Total) VALUES 
        (1, '2024-01-01 00:00:00', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', 3.96),
        (1, '2024-02-11 00:00:00', 'Av. Brigadeiro Faria Lima, 2170', 'São José dos Campos', 'SP', 'Brazil', '12227-000', 5.94),
        (2, '2024-01-03 00:00:00', 'Theodor-Heuss-Straße 34', 'Stuttgart', NULL, 'Germany', '70174', 1.98),
        (7, '2024-03-15 00:00:00', '541 Del Medio Avenue', 'Mountain View', 'CA', 'USA', '94040-111', 13.86),
        (9, '2024-04-09 00:00:00', 'Rua Dr. Falcão Filho, 155', 'São Paulo', 'SP', 'Brazil', '01007-010', 8.91);

    INSERT INTO InvoiceLine (InvoiceId, TrackId, UnitPrice, Quantity) VALUES 
        (1, 1, 0.99, 1),
        (1, 2, 0.99, 1),
        (1, 3, 0.99, 1),
        (1, 4, 0.99, 1),
        (2, 4, 1.29, 2),
        (2, 5, 0.99, 1),
        (3, 6, 1.29, 1),
        (4, 1, 0.99, 4),
        (4, 4, 1.29, 3),
        (5, 7, 1.49, 3);

    INSERT INTO Products (Name, Category, Price, StockQuantity) VALUES 
        ('Studio Monitor Headphones', 'Electronics', 149.99, 50),
        ('USB Condenser Microphone', 'Electronics', 89.95, 35),
        ('Acoustic Foam Panels (12-pack)', 'Studio Gear', 45.00, 120),
        ('MIDI Keyboard Controller 49-Key', 'Instruments', 199.00, 25),
        ('Guitar Audio Interface 2x2', 'Audio', 119.50, 40);

    INSERT INTO Orders (CustomerId, OrderDate, OrderStatus, TotalAmount) VALUES 
        (1, '2024-05-10', 'DELIVERED', 239.94),
        (2, '2024-05-12', 'SHIPPED', 89.95),
        (7, '2024-05-18', 'PROCESSING', 149.99),
        (9, '2024-05-20', 'DELIVERED', 318.50);
    """)

    conn.commit()
    conn.close()
    logger.info(f"Synthetic enterprise database successfully seeded at {db_path}.")


def _train_vector_store(db_path: str):
    """Seed Vanna and semantic vector store with initial schemas and business rules."""
    try:
        from core.database import DatabaseEngine
        from core.config import DatabaseConfig

        db = DatabaseEngine(DatabaseConfig(dialect="sqlite", sqlite_path=db_path))
        vanna_engine = VannaTextToSQLEngine()

        ddls = db.get_all_ddls()
        for tbl, ddl in ddls.items():
            vanna_engine.train_ddl(ddl, table_name=tbl)

        # Seed domain documentation
        vanna_engine.train_documentation(
            "InvoiceLine total sales is calculated as UnitPrice * Quantity."
        )
        vanna_engine.train_documentation(
            "Customer Country values are stored in full English name (e.g. 'Brazil', 'Germany', 'USA')."
        )
        vanna_engine.train_documentation(
            "Top selling artists should be ranked by SUM(InvoiceLine.UnitPrice * InvoiceLine.Quantity)."
        )

        # Seed golden training SQL queries
        vanna_engine.train_sql(
            question="What are the total sales for customers in Brazil?",
            sql="""WITH BrazilSales AS (
    SELECT c.Country, SUM(i.Total) AS TotalRevenue
    FROM Customer c
    JOIN Invoice i ON c.CustomerId = i.CustomerId
    WHERE c.Country = 'Brazil'
    GROUP BY c.Country
)
SELECT * FROM BrazilSales;"""
        )
        vanna_engine.train_sql(
            question="Find the top 5 artists with the most track sales",
            sql="""WITH TopArtists AS (
    SELECT art.Name AS ArtistName, ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS TotalSales
    FROM Artist art
    JOIN Album a ON art.ArtistId = a.ArtistId
    JOIN Track t ON a.AlbumId = t.AlbumId
    JOIN InvoiceLine il ON t.TrackId = il.TrackId
    GROUP BY art.ArtistId, art.Name
    ORDER BY TotalSales DESC
    LIMIT 5
)
SELECT * FROM TopArtists;"""
        )
        logger.info("Vector store seeded with DDLs and golden SQL pairs.")
    except Exception as e:
        logger.warning(f"Vector store training notice: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_database()
