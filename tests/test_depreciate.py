import datetime
import unittest
from decimal import Decimal

from beancount.core.compare import compare_entries
from beancount.core.data import Transaction, Open
from beancount.loader import load_string

import tests.util


def tx_normal(date: datetime.date, narration: str) -> Transaction:
    return tests.util.make_transaction(
        date=date,
        payee='Tesla',
        narration=narration,
        account_from='Liabilities:CreditCard:0001',
        account_to='Assets:Car:ModelX',
        amount='200000',
    )


def tx_depreciated(date: datetime.date, narration: str) -> Transaction:
    return tests.util.make_transaction(
        date=date,
        payee='Tesla',
        narration=narration,
        account_from='Assets:Car:ModelX',
        account_to='Expenses:Depreciation:Car:ModelX',
        amount='24000',
    )


class DepreciateTest(unittest.TestCase):
    def test_quantum_rounds_periods_and_puts_residual_in_final_period(self):
        journal_str = """
plugin "beancount_periodic.depreciate" "{'quantum':'0.01'}"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Equipment USD
2022-01-01 * "Equipment"
  Liabilities:CreditCard:0001    -100.00 USD
  Assets:Equipment
    depreciate: "3 Year /Yearly"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(errors, [])

        depreciation_txns = [e for e in entries
                             if isinstance(e, Transaction) and 'Depreciated' in e.narration]
        amounts = [next(p.units.number for p in tx.postings
                        if 'Depreciation' in p.account)
                   for tx in depreciation_txns]

        self.assertEqual(amounts, [Decimal('33.33'), Decimal('33.34'), Decimal('33.33')])
        self.assertEqual(sum(amounts), Decimal('100.00'))
        self.assertTrue(all(amount == amount.quantize(Decimal('0.01')) for amount in amounts))

    def test_quantum_rejects_incompatible_depreciable_amount(self):
        journal_str = """
plugin "beancount_periodic.depreciate" "{'quantum':'0.01'}"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Equipment USD
2022-01-01 * "Equipment"
  Liabilities:CreditCard:0001    -100.001 USD
  Assets:Equipment
    depreciate: "3 Year /Yearly"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 1)
        self.assertIn(
            'Depreciable amount 100.001 is not an exact multiple of quantum 0.01',
            errors[0].message,
        )

    def test_simple(self):
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
1900-01-01 open Expenses:Depreciation:Car:ModelX USD
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        expected_entries = [
            tx_normal(datetime.date(2022, 3, 31), 'Model X'),
            tx_depreciated(datetime.date(2022, 3, 31), 'Model X Depreciated(1/5)'),
            tx_depreciated(datetime.date(2023, 3, 31), 'Model X Depreciated(2/5)'),
            tx_depreciated(datetime.date(2024, 3, 31), 'Model X Depreciated(3/5)'),
            tx_depreciated(datetime.date(2025, 3, 31), 'Model X Depreciated(4/5)'),
            tx_depreciated(datetime.date(2026, 3, 31), 'Model X Depreciated(5/5)'),
        ]

        same, missing1, missing2 = compare_entries(list(tests.util.get_transactions_cleaned(entries)), expected_entries)
        self.assertTrue(same)

    def test_generate_until_01(self):
        journal_str = """
plugin "beancount_periodic.depreciate" "{'generate_until':'2024-03-31'}"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
1900-01-01 open Expenses:Depreciation:Car:ModelX USD
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
        """
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        expected_entries = [
            tx_normal(datetime.date(2022, 3, 31), 'Model X'),
            tx_depreciated(datetime.date(2022, 3, 31), 'Model X Depreciated(1/5)'),
            tx_depreciated(datetime.date(2023, 3, 31), 'Model X Depreciated(2/5)'),
            tx_depreciated(datetime.date(2024, 3, 31), 'Model X Depreciated(3/5)'),
        ]

        same, missing1, missing2 = compare_entries(list(tests.util.get_transactions_cleaned(entries)), expected_entries)
        self.assertTrue(same)

    def test_fractional_year_half(self):
        """Test 0.5 Year depreciation (6 months) with auto-open"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
2022-01-01 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -12000 USD
  Assets:Car:ModelX
    depreciate: "0.5 Year /Monthly"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # 0.5 Year with Monthly step should produce 6 depreciation transactions
        depreciation_txns = [e for e in entries
                             if isinstance(e, Transaction) and 'Depreciated' in e.narration]
        self.assertEqual(len(depreciation_txns), 6)

        # Verify auto-open was generated
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        self.assertEqual(len(expense_opens), 1)
        self.assertEqual(expense_opens[0].account, 'Expenses:Depreciation:Car:ModelX')

    def test_fractional_year_27_5(self):
        """Test 27.5 Year depreciation for real estate with auto-open"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:Mortgage USD
1900-01-01 open Assets:RealEstate:Building USD
2022-01-01 * "Property" "Building Purchase"
  Liabilities:Mortgage    -275000 USD
  Assets:RealEstate:Building
    depreciate: "27.5 Year /Yearly"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # 27.5 years with Yearly step should produce 28 depreciation transactions
        # (27 full years + 1 partial year)
        depreciation_txns = [e for e in entries
                             if isinstance(e, Transaction) and 'Depreciated' in e.narration]
        self.assertEqual(len(depreciation_txns), 28)

        # Verify auto-open was generated
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        self.assertEqual(len(expense_opens), 1)
        self.assertEqual(expense_opens[0].account, 'Expenses:Depreciation:RealEstate:Building')

        # Get depreciation amounts from expense postings
        def get_expense_amount(txn):
            for p in txn.postings:
                if 'Depreciation' in p.account:
                    return p.units.number
            return None

        # The last transaction should be roughly half the amount of a full year
        full_year_amount = get_expense_amount(depreciation_txns[0])
        last_txn_amount = get_expense_amount(depreciation_txns[-1])
        # Last transaction should be significantly less than a full year (roughly half)
        self.assertLess(last_txn_amount, full_year_amount * Decimal('0.6'))

    def test_auto_open_directive(self):
        """Test that open directive is auto-generated for expense account"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # Check that Open directive was generated for the expense account
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        self.assertEqual(len(expense_opens), 1)
        self.assertEqual(expense_opens[0].account, 'Expenses:Depreciation:Car:ModelX')
        self.assertEqual(expense_opens[0].currencies, ['USD'])

    def test_auto_open_no_duplicate(self):
        """Test that no duplicate open directives are created"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
1900-01-01 open Expenses:Depreciation:Car:ModelX USD
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # When expense account already exists, no additional open should be created
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        self.assertEqual(len(expense_opens), 1)  # Only the original one

    def test_auto_open_multiple_assets(self):
        """Test auto-open with multiple assets in same file"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
1900-01-01 open Assets:Car:ModelY USD
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
2022-04-01 * "Tesla" "Model Y"
  Liabilities:CreditCard:0001    -100000 USD
  Assets:Car:ModelY
    depreciate: "3 Year /Yearly =40000"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # Check that separate Open directives were generated for each expense account
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        self.assertEqual(len(expense_opens), 2)
        expense_accounts = {o.account for o in expense_opens}
        self.assertIn('Expenses:Depreciation:Car:ModelX', expense_accounts)
        self.assertIn('Expenses:Depreciation:Car:ModelY', expense_accounts)

    def test_custom_depreciate_account_auto_open(self):
        """Test auto-open respects custom depreciate_account metadata"""
        journal_str = """
plugin "beancount_periodic.depreciate"
1900-01-01 open Liabilities:CreditCard:0001 USD
1900-01-01 open Assets:Car:ModelX USD
  depreciate_account: "Expenses:Auto:Depreciation"
2022-03-31 * "Tesla" "Model X"
  Liabilities:CreditCard:0001    -200000 USD
  Assets:Car:ModelX
    depreciate: "5 Year /Yearly =80000"
"""
        entries, errors, options_map = load_string(journal_str)
        self.assertEqual(len(errors), 0)

        # Check that Open directive was generated for the custom expense account
        open_directives = [e for e in entries if isinstance(e, Open)]
        expense_opens = [o for o in open_directives if 'Depreciation' in o.account]
        # Should have one auto-generated open for the custom account
        custom_opens = [o for o in expense_opens if o.account == 'Expenses:Auto:Depreciation']
        self.assertEqual(len(custom_opens), 1)


if __name__ == '__main__':
    unittest.main()
