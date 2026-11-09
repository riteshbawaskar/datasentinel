@ui @requires_browser
Feature: UI automation with Playwright
  As a QA engineer
  I want to drive the application UI and cross-check it with the database
  So that what users see is what the data layer holds

  Scenario: The search box filters the customer grid
    Given I open the page "data/demo_site/index.html"
    Then the element "#heading" should contain the text "Customer Directory"
    When I fill "#name-filter" with "Customer 1"
    And I click "#search"
    Then the element "#result-count" should contain the text "Showing 11 of 30 customers"
    And there should be 30 elements matching "#customers tbody tr"
    When I take a screenshot named "Filtered grid"

  Scenario: The customer count on screen matches the database
    Given I open the page "data/demo_site/index.html"
    Then the text of "#customers tbody tr:first-child td:first-child" should equal the value returned by "SELECT MIN(CUSTOMER_ID) FROM customers" on connection "demo_db"

  Scenario: The UI customer grid matches the database table
    Given the compare config "compare_configs/customers_db_vs_web_grid.yml"
    When I run the data comparison
    Then the data comparison should pass

  @demo_fail
  Scenario: A wrong UI expectation is reported with a screenshot
    Given I open the page "data/demo_site/index.html"
    Then the element "#heading" should contain the text "Order Directory"
