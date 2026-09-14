"""Tests for the contact management system.

Run from the project folder with:

    python -m unittest -v test_contacts.py

Each test uses its own temporary database, so running the suite never touches
contacts.db. The application builds its Tkinter window at import time, so a
minimal stand-in for tkinter is installed first; that lets the tests call the
real button handlers without needing a display.
"""

import os
import sys
import types
import shutil
import sqlite3
import tempfile
import unittest


# ---------------------------------------------------------------------------
# Minimal tkinter stand-in
# ---------------------------------------------------------------------------
# Only the handful of widgets and methods the application actually uses are
# implemented. Listbox records what was inserted so tests can read the display,
# and messagebox records every dialog so tests can assert which one appeared.
def install_tkinter_stub():
    tk = types.ModuleType('tkinter')
    tk.VERTICAL = 'vertical'
    tk.RIGHT, tk.LEFT, tk.TOP, tk.BOTTOM = 'right', 'left', 'top', 'bottom'
    tk.BOTH, tk.X, tk.Y, tk.END = 'both', 'x', 'y', 'end'

    class Widget:
        def __init__(self, *a, **k):
            self.options = dict(k)

        def place(self, **k):
            return self

        def pack(self, **k):
            return self

        def config(self, **k):
            self.options.update(k)
            return self

        def bind(self, *a, **k):
            return self

        def yview(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

    class Root(Widget):
        def geometry(self, *a):
            pass

        def title(self, *a):
            pass

        def resizable(self, *a):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            self.destroyed = True

    class Listbox(Widget):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.items = []
            self.selection = ()

        def delete(self, first, last=None):
            self.items = []

        def insert(self, index, text):
            self.items.append(text)

        def curselection(self):
            return self.selection

        def choose(self, index):
            """Test helper: highlight a row."""
            self.selection = (index,)

        def clear_choice(self):
            self.selection = ()

    class StringVar:
        def __init__(self, *a, **k):
            self._value = ''

        def get(self):
            return self._value

        def set(self, value):
            self._value = value

    tk.Tk = Root
    tk.Frame = tk.Label = tk.Entry = tk.Button = tk.Scrollbar = Widget
    tk.Listbox = Listbox
    tk.StringVar = StringVar

    messagebox = types.ModuleType('tkinter.messagebox')
    messagebox.log = []
    messagebox.answer = True

    def showinfo(title, message):
        messagebox.log.append(('info', title, message))

    def showerror(title, message):
        messagebox.log.append(('error', title, message))

    def askyesno(title, message):
        messagebox.log.append(('question', title, message))
        return messagebox.answer

    messagebox.showinfo = showinfo
    messagebox.showerror = showerror
    messagebox.askyesno = askyesno

    tk.messagebox = messagebox
    sys.modules['tkinter'] = tk
    sys.modules['tkinter.messagebox'] = messagebox
    return messagebox


MESSAGES = install_tkinter_stub()

MODULE = 'contact_database_management_system'
SAMPLE = [
    ('Josh Smith', '07700 900123'),
    ('josh smith', '07700-900456'),
    ('Joshua Smyth', '07700900789'),
    ('Amara Okafor', '+44 7700 900222'),
    ('Ben Adeyemi', '07700 900333'),
    ('Priya Smithson', '07700 900444'),
]


class ContactsTestCase(unittest.TestCase):
    """Loads the application against a throwaway database."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp()
        cls.previous = os.getcwd()
        cls.source = os.path.join(cls.previous, MODULE + '.py')
        shutil.copy(cls.source, cls.folder)
        os.chdir(cls.folder)
        sys.path.insert(0, cls.folder)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous)
        shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        """Start each test from an empty database and a fresh import."""
        sys.modules.pop(MODULE, None)
        for leftover in ('contacts.db',):
            if os.path.exists(leftover):
                os.remove(leftover)
        MESSAGES.log.clear()
        MESSAGES.answer = True
        self.app = __import__(MODULE)

    def tearDown(self):
        self.app.connection.close()

    # -- helpers ----------------------------------------------------------
    def add(self, name, number, confirm=True):
        MESSAGES.answer = confirm
        self.app.name_var.set(name)
        self.app.number_var.set(number)
        self.app.add_contact()

    def add_sample(self):
        for name, number in SAMPLE:
            self.add(name, number)

    def displayed(self):
        return list(self.app.contact_listbox.items)

    def names_for(self, row_ids):
        return [self.app.display_names[row_id] for row_id in row_ids]

    def errors(self):
        return [entry for entry in MESSAGES.log if entry[0] == 'error']


class TestNormalisation(ContactsTestCase):

    def test_name_whitespace_and_case_are_folded(self):
        self.assertEqual(self.app.normalise_name('  Josh   SMITH '),
                         'josh smith')

    def test_numbers_reduce_to_digits(self):
        for written in ('07700 900123', '07700-900123', '(07700) 900123'):
            self.assertEqual(self.app.normalise_number(written), '07700900123')


class TestSchema(ContactsTestCase):

    def test_table_holds_only_name_and_number(self):
        self.app.cursor.execute('SELECT * FROM contacts')
        columns = [column[0] for column in self.app.cursor.description]
        self.assertEqual(columns, ['id', 'name', 'number'])

    def test_name_and_number_are_required(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.cursor.execute(
                'INSERT INTO contacts (name, number) VALUES (?, ?)',
                (None, '07700900123'))


class TestIndexes(ContactsTestCase):

    def test_names_that_differ_only_by_case_share_one_bucket(self):
        """Separate chaining: both records sit under the same key."""
        self.add('Josh Smith', '07700900123')
        self.add('josh smith', '07700900456')
        self.assertEqual(len(self.app.name_buckets['josh smith']), 2)

    def test_number_index_holds_a_single_row_per_key(self):
        self.add_sample()
        for row_id in self.app.number_lookup.values():
            self.assertIsInstance(row_id, int)
        self.assertEqual(len(self.app.number_lookup), len(SAMPLE))

    def test_every_word_of_a_name_becomes_a_searchable_key(self):
        self.add('Priya Smithson', '07700900444')
        self.assertIn('priya', self.app.sorted_words)
        self.assertIn('smithson', self.app.sorted_words)

    def test_word_list_is_sorted(self):
        self.add_sample()
        self.assertEqual(self.app.sorted_words, sorted(self.app.sorted_words))

    def test_indexes_are_rebuilt_after_a_write(self):
        self.add_sample()
        before = len(self.app.alphabetical_ids)
        self.add('Nia Boateng', '07700900555')
        self.assertEqual(len(self.app.alphabetical_ids), before + 1)


class TestDisplayOrder(ContactsTestCase):

    def test_contacts_are_listed_alphabetically_not_by_insertion(self):
        self.add_sample()
        shown = self.displayed()
        self.assertEqual(shown, sorted(shown, key=self.app.normalise_name))
        self.assertNotEqual(shown, [name for name, _ in SAMPLE])


class TestNameSearch(ContactsTestCase):

    def test_forename_prefix(self):
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_name('jos')),
                         ['Josh Smith', 'josh smith', 'Joshua Smyth'])

    def test_surname_prefix(self):
        """Regression test. An earlier version keyed the index on the whole
        name, so a surname prefix matched nothing at all."""
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_name('sm')),
                         ['Josh Smith', 'josh smith', 'Joshua Smyth',
                          'Priya Smithson'])

    def test_longer_surname_prefix_narrows_the_result(self):
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_name('smith')),
                         ['Josh Smith', 'josh smith', 'Priya Smithson'])

    def test_search_is_case_insensitive(self):
        self.add_sample()
        self.assertEqual(self.app.search_by_name('SMITH'),
                         self.app.search_by_name('smith'))

    def test_multiple_words_must_all_match(self):
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_name('josh smith')),
                         ['Josh Smith', 'josh smith'])

    def test_results_come_back_in_alphabetical_order(self):
        self.add_sample()
        found = self.names_for(self.app.search_by_name('sm'))
        self.assertEqual(found, sorted(found, key=self.app.normalise_name))

    def test_no_match_returns_nothing(self):
        self.add_sample()
        self.assertEqual(self.app.search_by_name('zz'), [])

    def test_empty_query_returns_everyone(self):
        self.add_sample()
        self.assertEqual(len(self.app.search_by_name('')), len(SAMPLE))


class TestNumberSearch(ContactsTestCase):

    def test_exact_number(self):
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_number('07700900456')),
                         ['josh smith'])

    def test_punctuation_and_spacing_are_ignored(self):
        self.add_sample()
        self.assertEqual(self.app.search_by_number('07700 900 456'),
                         self.app.search_by_number('07700-900456'))

    def test_number_stored_with_a_country_code(self):
        self.add_sample()
        self.assertEqual(self.names_for(self.app.search_by_number('+447700900222')),
                         ['Amara Okafor'])

    def test_unknown_number_returns_nothing(self):
        self.add_sample()
        self.assertEqual(self.app.search_by_number('07000000000'), [])


class TestSearchBox(ContactsTestCase):

    def test_a_query_with_letters_searches_names(self):
        self.add_sample()
        self.app.search_var.set('sm')
        self.app.run_search()
        self.assertEqual(len(self.displayed()), 4)

    def test_a_query_of_digits_searches_numbers(self):
        self.add_sample()
        self.app.search_var.set('07700900333')
        self.app.run_search()
        self.assertEqual(self.displayed(), ['Ben Adeyemi'])

    def test_a_failed_search_reports_no_matches(self):
        self.add_sample()
        MESSAGES.log.clear()
        self.app.search_var.set('zz')
        self.app.run_search()
        self.assertTrue(any('No matching' in entry[2] for entry in MESSAGES.log))

    def test_show_all_restores_the_full_list(self):
        self.add_sample()
        self.app.search_var.set('sm')
        self.app.run_search()
        self.app.clear_search()
        self.assertEqual(len(self.displayed()), len(SAMPLE))


class TestValidation(ContactsTestCase):

    def test_a_blank_field_is_refused(self):
        self.add('', '07700900123')
        self.assertTrue(self.errors())
        self.assertEqual(self.displayed(), [])

    def test_a_number_already_in_use_is_refused(self):
        self.add('Josh Smith', '07700900123')
        MESSAGES.log.clear()
        self.add('Someone Else', '07700 900 123')
        self.assertTrue(any('already saved' in entry[2] for entry in self.errors()))
        self.assertEqual(len(self.displayed()), 1)

    def test_a_duplicate_name_is_queried_and_can_be_declined(self):
        self.add('Josh Smith', '07700900123')
        MESSAGES.log.clear()
        self.add('Josh Smith', '07700900999', confirm=False)
        self.assertTrue(any(entry[0] == 'question' for entry in MESSAGES.log))
        self.assertEqual(len(self.displayed()), 1)

    def test_a_duplicate_name_can_be_accepted(self):
        self.add('Josh Smith', '07700900123')
        self.add('Josh Smith', '07700900999', confirm=True)
        self.assertEqual(len(self.displayed()), 2)


class TestActions(ContactsTestCase):

    def test_view_loads_the_selected_contact(self):
        self.add_sample()
        self.app.contact_listbox.choose(0)
        self.app.view_contact()
        self.assertEqual(self.app.name_var.get(), self.displayed()[0])

    def test_edit_changes_the_record_and_reorders_the_list(self):
        self.add_sample()
        self.app.contact_listbox.choose(0)          # Amara Okafor
        self.app.name_var.set('Zara Okafor')
        self.app.number_var.set('07700900222')
        self.app.update_contact()
        self.assertEqual(self.displayed()[-1], 'Zara Okafor')

    def test_edit_rejects_a_number_belonging_to_someone_else(self):
        self.add_sample()
        self.app.contact_listbox.choose(0)
        self.app.name_var.set('Amara Okafor')
        self.app.number_var.set('07700900333')      # Ben Adeyemi's number
        MESSAGES.log.clear()
        self.app.update_contact()
        self.assertTrue(self.errors())

    def test_edit_allows_a_contact_to_keep_its_own_number(self):
        self.add('Josh Smith', '07700900123')
        self.app.contact_listbox.choose(0)
        self.app.name_var.set('Joshua Smith')
        self.app.number_var.set('07700900123')
        self.app.update_contact()
        self.assertEqual(self.displayed(), ['Joshua Smith'])

    def test_delete_removes_the_contact(self):
        self.add_sample()
        self.app.contact_listbox.choose(0)
        self.app.delete_contact()
        self.assertEqual(len(self.displayed()), len(SAMPLE) - 1)

    def test_delete_can_be_cancelled(self):
        self.add_sample()
        self.app.contact_listbox.choose(0)
        MESSAGES.answer = False
        self.app.delete_contact()
        self.assertEqual(len(self.displayed()), len(SAMPLE))

    def test_reset_clears_the_entry_fields(self):
        self.app.name_var.set('Josh Smith')
        self.app.number_var.set('07700900123')
        self.app.reset_fields()
        self.assertEqual((self.app.name_var.get(), self.app.number_var.get()),
                         ('', ''))

    def test_actions_warn_instead_of_failing_when_nothing_is_selected(self):
        self.add_sample()
        self.app.contact_listbox.clear_choice()
        MESSAGES.log.clear()
        self.app.view_contact()
        self.app.update_contact()
        self.app.delete_contact()
        self.assertEqual(len(self.errors()), 3)


class TestPersistence(ContactsTestCase):

    def test_contacts_survive_a_restart(self):
        self.add_sample()
        self.app.connection.commit()
        saved = self.displayed()

        sys.modules.pop(MODULE, None)
        reopened = __import__(MODULE)
        self.addCleanup(reopened.connection.close)
        self.assertEqual(list(reopened.contact_listbox.items), saved)


if __name__ == '__main__':
    unittest.main(verbosity=2)
