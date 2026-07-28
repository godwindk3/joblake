# joblake

Website-specific crawling is implemented through source adapters. See
[Adding a job source](docs/adding-source.md) for the extension workflow.

Raw detail HTML is stored in MinIO and crawl state is stored in SQLite.
See [MinIO raw storage and SQLite state](docs/storage-state.md) for the
runtime configuration, state model, validation flow, and future parser
query.

`` 
System design:
+ 01 Product Requirements
+ 02 Architecture
+ 03 Data Model
+ 04 Pipeline
+ 05 Source Catalog
+ 06 Data Dictionary
+ 07 NFR
+ 08 Data Quality
+ 09 Canonical Model
+ 10 Dedup Strategy
+ 11 Taxonomy
+ 12 Infrastructure
+ 13 Monitoring
+ 14 Security
+ 15 Crawler / Ingestion Strategy
+ 16 Data Lifecycle & Retention Policy
+ 17 CI/CD & Schema Evolution 

``

``` 
+ Source(website, facebook)

+ Salary: Cụ thể số, thỏa thuận, you will like it, attractive,...

+ benefit

+ requirement basic/ detail

+ job title

+ field: it, ...

+ job description

+ time working

+ location

+ submission deadline (apply deadline)

+ company information

+ common infor

+ skills

+ job domain

+ experience
```
