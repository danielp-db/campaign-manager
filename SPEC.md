I would like to create a Databricks Demo that reproduces a Platform to create marketing campaigns for a Telco with low-code/no-code capabilities.

The main screen would show all running cammpaigns and all future campaigns as well as all campaigns that need to be approved by compliance.

A campaign basically has a couple of items:
- Campaign Info
- Campaign Logic
- Analytics

# Campaign Info
Basically shows who created the campaign object, priority, organization, when was data last refresh, number of leads, number of unique sub accounts, etc.

# Campaign Logic
This is the core of the application, this will be a low-code/no-code functionality that lets you build simple pipelines with any table in Unity Catalog and any uploaded .csv/excel file.
You choose your sources, choose filters, you can create new columns and do joins. All of this is visualized in a DAG.

Once the logic is finalized you can save the definition and run the pipeline, the results can be saved in a table for all campaigns.
(You later can edit the pipeline within the app)

# Analytics
The analytics functionality reads tables of the ongoing results for each campaing and displays them as a dashboard.

Use the following assets:
- Create a Databricks Asset Bundle
- Use the workspace - https://fevm-att-log-anomaly.cloud.databricks.com/
- Use lakebase to store sessions
- use catalog att_log_anomaly_catalog
- Use schema prospector_pro
- Follow the best practices laid in the following links:
    - https://databricks.github.io/appkit/docs/
    - https://apps-cookbook.dev/ 
- We can use as base for the query builder something like
    - https://github.com/fpatano/visualquerybuilder
- If building any asset, prepended with "ProspectorPro_"


Instead of using a DAG to define the Campaign Builder Logic, use buttonts to create elements as defined below.

Have the following options to create nodes:
- Add DataSet
    - Inputs:
        - A dropdown where you can choose Unity Catalog table or File
            - If Unity Catalog Table, a dropdown that show all tables in the att_log_anomaly_catalog catalog
            - If File, a button to upload a csv file
            - Name of TemporaryDataSet Output
    - Output:
        - A TemporaryDataSet
            - Node which reflects a CTE in the SQL query behind the campaign logic of a SELECT * FROM <unity_catalog_table> or a SELECT * FROM read_files(<details>) depending on the chosen option
- Add Filter
    - Inputs:
        - A dropdown with the existing TemporaryDataSets in the current definition
        - A column name from the chosen TemporaryDataSet
        - A way to define the filter (greater than, less than, equal, etc)
        - Name of TemporaryDataSet Output
            - Node which reflects a CTE in the SQL query behind the compaign logic of a WHERE predicate applied on the input TemporaryDataSet
    - Output:
        - A TemporaryDataSet
- Add Field
    - Inputs:
        - A dropdown with the existing TemporaryDataSets in the current definition
        - A textbox to fill with a SQL statement
        - Name of TemporaryDataSet Output
    - Output
        - A TemporaryDataSet
            - Node which reflects a CTE in the SQL query behind the compaign logic of a field creation according to the SQL Statement in the textbox
- Select Field
    - Inputs:
        - A dropdown with the existing TemporaryDataSets in the current definition
        - A way to add as many columns from the exisiting TemporaryDataSet and an option to rename them if needed
        - Name of TemporaryDataSet Output
    - Output
        - A TemporaryDataSet
            - Node which reflects a CTE in the SQL query behind the compaign logic of a SELECT ... FROM the input TemporaryDataSet with any column selection and aliases
- Add Join
    - Inputs:
        - Two dropdowns for Left and Right TemporaryDataSets in the current definition
        - A dropdown defining type of join
        - A dropdown defining the fields to join by
        - Name of TemporaryDataSet Output
    - Output
        - A TemporaryDataSet
            - Node which reflects a CTE in the SQL query which represents the JOIN between the two TemporaryDatasets (CTEs)
- Add Union
    - Inputs:
        - Two dropdowns for Left and Right TemporaryDataSets in the current definition
        - Name of TemporaryDataSet Output
    - Output
        - Node which reflects a CTE in the SQL query which represents the UNION between the two TemporaryDatasets (CTEs)

