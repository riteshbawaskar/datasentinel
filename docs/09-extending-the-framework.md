# 9. Extending the framework

## Add a database

1. Create `datasentinel/connectors/mydb_connector.py`:
   ```python
   from datasentinel.connectors.base import BaseConnector, cursor_to_df

   class MyDbConnector(BaseConnector):
       type_name = "mydb"
       def connect(self):
           import mydb_driver                          # import lazily
           self._conn = mydb_driver.connect(host=self.config["host"], password=self.config["password"])
       def fetch_df(self, query):
           cur = self._conn.cursor(); cur.execute(query)
           try: return cursor_to_df(cur)               # any DB-API cursor
           finally: cur.close()
       def close(self): self._conn.close()
   ```
2. Register it in `datasentinel/connectors/factory.py`:
   `"mydb": ("datasentinel.connectors.mydb_connector", "MyDbConnector"),`
3. Use it: `connections: {mydb_qa: {type: mydb, host: ..., password: ENC(...)}}`. Secrets are decrypted automatically.

## Add a validation check

```python
# datasentinel/validators/data_validator.py
@register("positive_balance")
def _positive_balance(v, df, spec):
    bad = pd.to_numeric(df["BALANCE"], errors="coerce") < 0      # True = invalid row
    return [v.bad_rows(spec, "positive_balance", spec.get("name", "BALANCE"), df, bad, "BALANCE >= 0")]
```
Use it: `- {type: positive_balance}`. Return several outcomes (one per column) for precise reporting.

## Add a comparison option

Add a field to `CompareOptions` (`dataset_comparator.py`), then use it in `_equal_non_null`. It is immediately
configurable under `options:` and typos in option names are rejected automatically.

## Add steps

Create any `features/steps/*.py`; behave loads them all. Record results with `datasentinel.bdd.checkpoint`.

## Add report content

`context.store.info(key, value)` adds a fact chip, `context.store.attach_image(title, png_bytes)` a screenshot,
and `checkpoint(..., tables=[Table.from_df("Title", df)])` an evidence table.

## Rename the framework

Edit `datasentinel/branding.py` (name, tagline, version). Reports, console banner and the BDD report follow.

## Tests for your changes

`pytest -q` runs `tests/test_framework.py` (no cloud access or browser needed); add a test for each new check/option.
