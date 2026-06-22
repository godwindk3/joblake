# 🌊 JobLake System Architecture

> A lightweight, scalable data engineering pipeline designed to scrape, standardize, validate, and index job market data with high performance.

---

## 🏗️ Architecture Diagram

The system implements a **Medallion Architecture** (Bronze, Silver, Gold), orchestrated by Apache Airflow, with a strict Data Contract validation step using Pydantic.

```mermaid
graph TD
    %% Control Plane - Orchestration
    subgraph Control_Plane [Orchestration]
        A([⚙️ Apache Airflow])
    end

    %% Data Sources
    subgraph Data_Sources [External Data]
        S[🌐 External Sources<br>IT Boards, Facebook]
    end

    %% Data Lake Layers
    subgraph Bronze [Bronze Layer - Raw Storage]
        M[(🪣 MinIO)]
    end

    subgraph Silver [Silver Layer - Processing]
        P[🐼 Python + Pandas]
    end

    %% Validation Layer
    subgraph Quality_Gate [Data Quality Gate]
        Q{🛡️ Pydantic}
    end

    %% Serving Layers
    subgraph Gold [Gold Layer - Serving]
        PG[(🐘 PostgreSQL)]
        ES[(🔍 Elasticsearch)]
    end

    subgraph Visualization [UI & Monitoring]
        K[📊 Kibana]
    end

    %% Data Flow Pathways (Solid Lines)
    S -- "Extract & Dump Raw (JSON/HTML)" --> M
    M -- "Read, Cleanse, Standardize" --> P
    P -- "Validate Schema & Types" --> Q
    Q -- "Valid Records: Load Relational" --> PG
    Q -- "Valid Records: Index Full-Text" --> ES
    Q -. "Invalid Records: Dead Letter Queue" .-> M

    %% Control Flow Pathways (Dotted Lines)
    A -. "Schedules & Triggers Scrapers" .-> S
    A -. "Triggers Pandas Pipeline" .-> P

    %% Component Styling
    classDef bronze fill:#cd7f32,stroke:#333,stroke-width:1px,color:#fff;
    classDef silver fill:#c0c0c0,stroke:#333,stroke-width:1px,color:#000;
    classDef quality fill:#4CAF50,stroke:#333,stroke-width:1px,color:#fff;
    classDef gold fill:#ffd700,stroke:#333,stroke-width:1px,color:#000;
    
    class M bronze;
    class P silver;
    class Q quality;
    class PG,ES gold;