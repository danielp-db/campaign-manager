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