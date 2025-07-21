# Test Suite for Matter Device Compliance Parser

## Test Structure

```
tests/
├── conftest.py                    # pytest fixtures
├── test_log_parser.py             # Tests for core/log_parser.py
├── test_compliance_checker.py     # Tests for core/compliance_checker.py
├── test_helper.py                 # Tests for utils/helper.py
├── test_datamodel_parser.py       # Tests for datamodel_parser.py CLI script
├── test_integration.py            # Integration tests
├── test_client_validation.py      # Client cluster validation tests
├── test_fix.py                    # Device type parsing fix tests
├── test_validation.py             # Validation logic tests
├── requirements.txt               # Test dependencies
└── README.md                      # This file
```

## Running Tests

### Install Dependencies

```bash
pip install -r tests/requirements.txt
```

### Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_log_parser.py -v

# Run with coverage
pytest --cov=core --cov=utils --cov=datamodel_parser tests/

# Run with verbose output and print statements
pytest tests/ -v -s
```

## Test Fixtures

Common fixtures in `conftest.py`:

- `sample_log_data`: Valid log data for testing
- `sample_parsed_data`: Pre-parsed data structure
- `sample_element_requirements`: Sample requirements for compliance testing
- `temp_requirements_file`: Temporary requirements file
- `invalid_log_data`: Invalid data for negative testing
- `mock_logger`: Mock logger for testing

## Adding New Tests

1. Create test methods in appropriate test file
2. Include both valid and invalid test cases
3. Use fixtures for common test data
4. Follow naming convention: `test_function_name_scenario`
