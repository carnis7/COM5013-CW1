"""Contact Management System - working baseline.

Stores names and phone numbers in SQLite and lets the user add, edit, view and
delete them through a Tkinter window. No search yet: the listbox shows every
contact in the order they were entered and the only way to reach a record is to
click it.
"""

import tkinter as tk
import tkinter.messagebox
import sqlite3

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
conn = sqlite3.connect('contacts.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY,
        name TEXT,
        number TEXT
    )
''')
conn.commit()

# Row ids currently in the listbox, in the same order, so that a selection
# index can be turned back into a database key.
contactlist = []

# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
root = tk.Tk()
root.geometry('800x650')
root.config(bg='#b6d7a8')
root.title('Contact Management System')
root.resizable(0, 0)

Name = tk.StringVar()
Number = tk.StringVar()

frame = tk.Frame(root)
frame.pack(side=tk.RIGHT)

scroll = tk.Scrollbar(frame, orient=tk.VERTICAL)
select = tk.Listbox(frame, yscrollcommand=scroll.set, font=('Times new roman', 16),
                    bg="#f0fffc", width=20, height=20, borderwidth=3, relief="groove")
scroll.config(command=select.yview)
scroll.pack(side=tk.RIGHT, fill=tk.Y)
select.pack(side=tk.LEFT, fill=tk.BOTH, expand=1)


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------
def Select_set():
    """Reload the listbox from the database."""
    cursor.execute("SELECT id, name FROM contacts")
    contactlist.clear()
    select.delete(0, tk.END)
    for row in cursor.fetchall():
        contactlist.append(row[0])
        select.insert(tk.END, row[1])


def Selected():
    """Index of the highlighted row, or None if nothing is highlighted."""
    if not select.curselection():
        tk.messagebox.showerror("Error", "Please Select the Name")
        return None
    return select.curselection()[0]


def AddContact():
    if Name.get() and Number.get():
        cursor.execute("INSERT INTO contacts (name, number) VALUES (?, ?)",
                       (Name.get(), Number.get()))
        conn.commit()
        Select_set()
        EntryReset()
        tk.messagebox.showinfo("Confirmation", "Successfully Added New Contact")
    else:
        tk.messagebox.showerror("Error", "Please fill in the information")


def UpdateDetail():
    selected = Selected()
    if selected is not None:
        if Name.get() and Number.get():
            cursor.execute("UPDATE contacts SET name=?, number=? WHERE id=?",
                           (Name.get(), Number.get(), contactlist[selected]))
            conn.commit()
            tk.messagebox.showinfo("Confirmation", "Successfully Updated Contact")
            EntryReset()
            Select_set()
        else:
            tk.messagebox.showerror("Error", "Please fill in the information")


def Delete_Entry():
    selected = Selected()
    if selected is not None:
        result = tk.messagebox.askyesno('Confirmation',
                                        'You Want to Delete the Contact You Selected')
        if result:
            cursor.execute("DELETE FROM contacts WHERE id=?",
                           (contactlist[selected],))
            conn.commit()
            Select_set()
    else:
        tk.messagebox.showerror("Error", 'Please select the Contact')


def VIEW():
    selected = Selected()
    if selected is not None:
        cursor.execute("SELECT name, number FROM contacts WHERE id=?",
                       (contactlist[selected],))
        name, number = cursor.fetchone()
        Name.set(name)
        Number.set(number)


def EntryReset():
    Name.set('')
    Number.set('')


def EXIT():
    conn.close()
    root.destroy()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
tk.Label(root, text='Name', font=("Times new roman", 25, "bold"),
         bg='orange').place(x=30, y=20)
tk.Entry(root, textvariable=Name, width=30).place(x=200, y=30)
tk.Label(root, text='Contact No.', font=("Times new roman", 22, "bold"),
         bg='SlateGray3').place(x=30, y=70)
tk.Entry(root, textvariable=Number, width=30).place(x=200, y=80)

tk.Button(root, text=" ADD", font='Helvetica 18 bold', bg='#e8c1c7',
          command=AddContact, padx=20).place(x=50, y=190)
tk.Button(root, text="EDIT", font='Helvetica 18 bold', bg='#e8c1c7',
          command=UpdateDetail, padx=20).place(x=50, y=250)
tk.Button(root, text="DELETE", font='Helvetica 18 bold', bg='#e8c1c7',
          command=Delete_Entry, padx=20).place(x=50, y=310)
tk.Button(root, text="VIEW", font='Helvetica 18 bold', bg='#e8c1c7',
          command=VIEW).place(x=50, y=375)
tk.Button(root, text="RESET", font='Helvetica 18 bold', bg='#e8c1c7',
          command=EntryReset).place(x=50, y=440)
tk.Button(root, text="EXIT", font='Helvetica 24 bold', bg='tomato',
          command=EXIT).place(x=250, y=520)

Select_set()
root.mainloop()
