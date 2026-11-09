@compare
Feature: Cross-source data comparison
  As a data engineer
  I want to compare recordsets between databases and Excel files
  So that I can prove migrations and pipelines move data without loss or corruption

  @demo
  Scenario: Customers in the database match the Excel extract
    Given the compare config "compare_configs/customers_db_vs_excel.yml"
    When I run the data comparison
    Then the source and target row counts should match
    And there should be no duplicate primary keys in the source
    And there should be no duplicate primary keys in the target
    And there should be no records missing in the target
    And there should be no records missing in the source
    And there should be no field mismatches

  @demo
  Scenario Outline: Compare configs can be batched with a single overall assertion
    Given the compare config "<config>"
    When I run the data comparison
    Then the data comparison should pass

    Examples:
      | config                                       |
      | compare_configs/customers_db_vs_excel.yml    |

  @demo_fail
  Scenario: Customers with known differences are detected
    Given the compare config "compare_configs/customers_db_vs_excel_diffs.yml"
    When I run the data comparison
    Then the source and target row counts should match
    And there should be no records missing in the target
    And there should be no records missing in the source
    And the field "NAME" should have no mismatches
    And there should be no field mismatches

  @demo
  Scenario: Known differences stay within the agreed tolerance
    Given the compare config "compare_configs/customers_db_vs_excel_diffs.yml"
    When I run the data comparison
    Then the field "NAME" should have no mismatches
    And the field "STATUS" should have no mismatches
    And the mismatch percentage should be at most 15

  @snowflake @requires_creds
  Scenario: Snowflake DEV and QA ORDERS are identical
    Given the compare config "compare_configs/snowflake_dev_vs_qa.yml"
    When I run the data comparison
    Then the data comparison should pass

  @oracle @snowflake @requires_creds
  Scenario: Oracle to Snowflake customer migration is complete
    Given the compare config "compare_configs/oracle_vs_snowflake.yml"
    When I run the data comparison
    Then the source and target row counts should match
    And there should be no records missing in the target
    And there should be no field mismatches

  @databricks @excel @requires_creds
  Scenario: Databricks prices match the signed-off Excel sheet
    Given the compare config "compare_configs/databricks_vs_excel.yml"
    When I run the data comparison
    Then the data comparison should pass
