READ Raw_ScreenTime CSV
READ App_Mappings.csv

FOR each app:
    find mapping
    validate mapping against config.taxonomy

    create Fact_Time record

aggregate Fact_Time by:
    Date
    Category
    Subcategory

validate:
    raw duration == Fact_Time duration

write:
    Fact_Time
    Daily_Time