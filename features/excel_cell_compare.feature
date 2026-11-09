@excel
Feature: Excel cell-to-cell comparison
  As a report owner
  I want to compare two workbooks cell by cell
  So that unintended changes between report versions are caught

  @demo
  Scenario: Cosmetic differences are ignored
    Given the excel compare config "cell_compare_configs/sales_v1_vs_v2_ok.yml"
    When I run the excel cell comparison
    Then both workbooks should contain the same sheets
    And there should be no cell differences

  @demo_fail
  Scenario: Changed cells are located precisely
    Given the excel compare config "cell_compare_configs/sales_v1_vs_v2_diff.yml"
    When I run the excel cell comparison
    Then both workbooks should contain the same sheets
    And the cell "A2" in sheet "Summary" should match
    And the sheet "Summary" should have no cell differences
    And the sheet "Targets" should have no cell differences
