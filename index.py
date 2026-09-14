"""Contact Management System.

A small Tkinter application that stores names and phone numbers in SQLite and
searches them through in-memory indexes. The data structures used here are:

  * an SQLite B-tree, keyed on the row id, for storage that survives a restart
  * a hash index on the full name, holding a list of ids per key (separate
    chaining), used to detect duplicate names in O(1)
  * a hash index on the phone number, holding a single id per key, since
    numbers are effectively unique
  * two sorted lists, one of full names for alphabetical display and one of
    individual words for prefix search by binary search
"""

import re
import bisect
import sqlite3
import tkinter as tk
import tkinter.messagebox

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# 'id INTEGER PRIMARY KEY' aliases SQLite's rowid, so rows are held in a
# B-tree keyed on id and lookups by id cost O(log n).
connection = sqlite3.connect('contacts.db')
cursor = connection.cursor()

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        number TEXT NOT NULL
    )
    """
)
connection.commit()

# ---------------------------------------------------------------------------
# Index state
# ---------------------------------------------------------------------------
# displayed_ids  row ids currently shown in the listbox, in the same order, so
#                a selection index maps to a database key in O(1)
# display_names  row id -> name as typed. The indexes hold normalised keys,
#                which are not what belongs on screen.
# name_buckets   normalised full name -> list of row ids. Names repeat, so each
#                key holds a bucket: separate chaining.
# number_lookup  normalised number -> one row id. Numbers are near-unique, so
#                a bucket would be wasted space.
# sorted_names / alphabetical_ids
#                parallel lists sorted by full normalised name, one entry per
#                contact, giving display order.
# sorted_words / word_owner_ids
#                parallel lists sorted by individual word. A contact appears
#                once per word of their name, so a surname is searchable too.
# alphabetical_position
#                row id -> position in display order, so search results can be
#                ordered without rescanning.
displayed_ids = []
display_names = {}
name_buckets = {}
number_lookup = {}
sorted_names = []
alphabetical_ids = []
sorted_words = []
word_owner_ids = []
alphabetical_position = {}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise_name(raw):
    """Collapse whitespace and case-fold a name.

    Case-folding induces collisions deliberately: 'Josh Smith' and
    'josh smith' are meant to land in the same bucket.
    """
    return ' '.join(raw.split()).casefold()


def normalise_number(raw):
    """Reduce a number to digits only, so '07700 900123', '07700-900123'
    and '07700900123' all produce the same key."""
    return re.sub(r'\D', '', raw)


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------
def build_indexes():
    """Rebuild every index from the database.

    Called once at start-up and after each write. A single O(n) pass fills the
    hash indexes; ordering the two key lists then costs O(n log n).
    """
    name_buckets.clear()
    number_lookup.clear()
    sorted_names.clear()
    alphabetical_ids.clear()
    sorted_words.clear()
    word_owner_ids.clear()
    alphabetical_position.clear()
    display_names.clear()

    cursor.execute("SELECT id, name, number FROM contacts")
    rows = cursor.fetchall()

    name_pairs = []
    word_pairs = []
    for row_id, name, number in rows:
        display_names[row_id] = name

        key = normalise_name(name)
        name_buckets.setdefault(key, []).append(row_id)   # chaining
        name_pairs.append((key, row_id))

        # set() so a repeated word does not list the same contact twice
        for word in set(key.split()):
            word_pairs.append((word, row_id))

        number_key = normalise_number(number)
        if number_key and number_key not in number_lookup:
            number_lookup[number_key] = row_id            # first row wins

    # list.sort() is Timsort. Below MAX_MINRUN elements it reduces to a binary
    # insertion sort, which is the right algorithm at this scale. Sorting here
    # rather than with ORDER BY avoids a second query.
    name_pairs.sort()
    word_pairs.sort()

    for position, (key, row_id) in enumerate(name_pairs):
        sorted_names.append(key)
        alphabetical_ids.append(row_id)
        alphabetical_position[row_id] = position

    for word, row_id in word_pairs:
        sorted_words.append(word)
        word_owner_ids.append(row_id)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def match_word_prefix(prefix):
    """Row ids whose name contains a word starting with prefix.

    Binary search finds the start of the range in O(log n); the matches are
    then walked in O(k). No hash index can answer this, because hashing
    destroys the ordering that makes a prefix a contiguous range.
    """
    matches = set()
    position = bisect.bisect_left(sorted_words, prefix)
    while position < len(sorted_words) and sorted_words[position].startswith(prefix):
        matches.add(word_owner_ids[position])
        position += 1
    return matches


def search_by_name(query):
    """Every word of the query must match some word of the name.

    So 'sm' finds Smith and Smithson, and 'jos sm' finds only contacts whose
    name matches both. Results come back in alphabetical order.
    """
    key = normalise_name(query)
    if not key:
        return list(alphabetical_ids)

    word_matches = [match_word_prefix(word) for word in key.split()]
    matches = set.intersection(*word_matches)
    return sorted(matches, key=lambda row_id: alphabetical_position[row_id])


def search_by_number(query):
    """Exact lookup through the number index, O(1) on average."""
    key = normalise_number(query)
    if not key:
        return list(alphabetical_ids)
    row_id = number_lookup.get(key)
    return [row_id] if row_id is not None else []


# ---------------------------------------------------------------------------
# Window and widgets
# ---------------------------------------------------------------------------
window = tk.Tk()
window.geometry('820x600')
window.config(bg='#eef2f5')
window.title('Contact Management System')
window.resizable(0, 0)

name_var = tk.StringVar()
number_var = tk.StringVar()
search_var = tk.StringVar()

list_frame = tk.Frame(window, bg='#eef2f5')
list_frame.pack(side=tk.RIGHT, padx=16, pady=16)

scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
contact_listbox = tk.Listbox(
    list_frame,
    yscrollcommand=scrollbar.set,
    font=('Segoe UI', 13),
    bg='#ffffff',
    width=26,
    height=22,
    borderwidth=1,
    relief='solid',
)
scrollbar.config(command=contact_listbox.yview)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
contact_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def show_contacts(row_ids=None):
    """Refresh the listbox. Defaults to every contact in alphabetical order."""
    if row_ids is None:
        row_ids = alphabetical_ids

    displayed_ids.clear()
    contact_listbox.delete(0, tk.END)
    for row_id in row_ids:
        displayed_ids.append(row_id)
        contact_listbox.insert(tk.END, display_names.get(row_id, ''))


def refresh_display():
    """Rebuild the indexes and redraw the list."""
    build_indexes()
    show_contacts()


def selected_index():
    """Index of the highlighted row, or None with a message if nothing is."""
    if not contact_listbox.curselection():
        tk.messagebox.showerror('Error', 'Please select a contact')
        return None
    return contact_listbox.curselection()[0]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def number_owner(number, ignore_id=None):
    """Row id already holding this number, ignoring one row, else None."""
    owner = number_lookup.get(normalise_number(number))
    if owner is None or owner == ignore_id:
        return None
    return owner


def duplicate_name_confirmed(name, ignore_id=None):
    """Warn if the name is already in use. True means go ahead.

    The name index answers this in O(1), and the chained bucket is what makes
    it possible to report how many existing contacts share the name.
    """
    existing = [row_id for row_id in name_buckets.get(normalise_name(name), [])
                if row_id != ignore_id]
    if not existing:
        return True

    if len(existing) == 1:
        wording = 'is already 1 contact'
    else:
        wording = 'are already {} contacts'.format(len(existing))
    return tk.messagebox.askyesno(
        'Duplicate name',
        'There {} with that name. Save anyway?'.format(wording),
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
def add_contact():
    """Insert a new contact after checking the number is not already held."""
    name = name_var.get().strip()
    number = number_var.get().strip()
    if not (name and number):
        tk.messagebox.showerror('Error', 'Please fill in the information')
        return

    # The number index makes this check O(1) rather than a table scan.
    owner = number_owner(number)
    if owner is not None:
        tk.messagebox.showerror(
            'Error',
            'That number is already saved under {}'.format(
                display_names.get(owner, 'another contact')),
        )
        return

    if not duplicate_name_confirmed(name):
        return

    cursor.execute("INSERT INTO contacts (name, number) VALUES (?, ?)",
                   (name, number))
    connection.commit()
    refresh_display()
    reset_fields()
    tk.messagebox.showinfo('Confirmation', 'Successfully added new contact')


def update_contact():
    """Overwrite the selected contact with the values in the entry fields."""
    index = selected_index()
    if index is None:
        return

    name = name_var.get().strip()
    number = number_var.get().strip()
    if not (name and number):
        tk.messagebox.showerror('Error', 'Please fill in the information')
        return

    row_id = displayed_ids[index]
    owner = number_owner(number, ignore_id=row_id)
    if owner is not None:
        tk.messagebox.showerror(
            'Error',
            'That number is already saved under {}'.format(
                display_names.get(owner, 'another contact')),
        )
        return

    if not duplicate_name_confirmed(name, ignore_id=row_id):
        return

    cursor.execute("UPDATE contacts SET name=?, number=? WHERE id=?",
                   (name, number, row_id))
    connection.commit()
    refresh_display()
    reset_fields()
    tk.messagebox.showinfo('Confirmation', 'Successfully updated contact')


def delete_contact():
    """Remove the selected contact after confirmation."""
    index = selected_index()
    if index is None:
        return
    if tk.messagebox.askyesno('Confirmation', 'Delete the selected contact?'):
        cursor.execute("DELETE FROM contacts WHERE id=?", (displayed_ids[index],))
        connection.commit()
        refresh_display()
        reset_fields()


def view_contact():
    """Load the selected contact into the entry fields."""
    index = selected_index()
    if index is None:
        return
    cursor.execute("SELECT name, number FROM contacts WHERE id=?",
                   (displayed_ids[index],))
    row = cursor.fetchone()
    if row:
        name_var.set(row[0])
        number_var.set(row[1])


def run_search():
    """Search by number if the query has no letters, otherwise by name."""
    query = search_var.get().strip()
    if not query:
        show_contacts()
        return

    if any(character.isalpha() for character in query):
        matches = search_by_name(query)
    else:
        matches = search_by_number(query)

    show_contacts(matches)
    if not matches:
        tk.messagebox.showinfo('Search', 'No matching contacts found')


def clear_search():
    """Empty the search box and show every contact again."""
    search_var.set('')
    show_contacts()


def reset_fields():
    """Blank the name and number entry fields."""
    name_var.set('')
    number_var.set('')


def close_app():
    """Close the database connection and shut the window."""
    connection.close()
    window.destroy()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
LABEL_FONT = ('Segoe UI', 14, 'bold')
BUTTON_FONT = ('Segoe UI', 12, 'bold')

tk.Label(window, text='Name', font=LABEL_FONT,
         bg='#eef2f5').place(x=36, y=36)
tk.Entry(window, textvariable=name_var, width=28,
         font=('Segoe UI', 12)).place(x=150, y=38)

tk.Label(window, text='Number', font=LABEL_FONT,
         bg='#eef2f5').place(x=36, y=82)
tk.Entry(window, textvariable=number_var, width=28,
         font=('Segoe UI', 12)).place(x=150, y=84)

tk.Label(window, text='Search', font=LABEL_FONT,
         bg='#eef2f5').place(x=36, y=140)
search_entry = tk.Entry(window, textvariable=search_var, width=28,
                        font=('Segoe UI', 12))
search_entry.place(x=150, y=142)
search_entry.bind('<Return>', lambda event: run_search())

tk.Button(window, text='Search', font=BUTTON_FONT, bg='#cfe0ec', width=10,
          command=run_search).place(x=150, y=176)
tk.Button(window, text='Show all', font=BUTTON_FONT, bg='#cfe0ec', width=10,
          command=clear_search).place(x=262, y=176)

tk.Button(window, text='Add', font=BUTTON_FONT, bg='#d8e6d2', width=12,
          command=add_contact).place(x=36, y=248)
tk.Button(window, text='Edit', font=BUTTON_FONT, bg='#d8e6d2', width=12,
          command=update_contact).place(x=36, y=294)
tk.Button(window, text='Delete', font=BUTTON_FONT, bg='#efd4d4', width=12,
          command=delete_contact).place(x=36, y=340)
tk.Button(window, text='View', font=BUTTON_FONT, bg='#d8e6d2', width=12,
          command=view_contact).place(x=36, y=386)
tk.Button(window, text='Reset', font=BUTTON_FONT, bg='#e4e4e4', width=12,
          command=reset_fields).place(x=36, y=432)
tk.Button(window, text='Exit', font=BUTTON_FONT, bg='#d9a7a7', width=12,
          command=close_app).place(x=36, y=496)

refresh_display()
window.mainloop()
