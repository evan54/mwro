import sys
import datetime as dtt
import re

import PySimpleGUIWeb as sg
from pony import orm
from pony.orm import Required, Optional, db_session

###############################################################################
# DATABASE
###############################################################################

db = orm.Database()


class Bottlefeeding(db.Entity):
    time = Required(dtt.datetime)
    ounces = Optional(float)
    comment = Optional(str)


class Breastfeeding(db.Entity):
    start_time = Required(dtt.datetime)
    end_time = Optional(dtt.datetime)
    is_left = Required(bool)
    used_shield = Required(bool)
    comment = Optional(str)


class Peeing(db.Entity):
    time = Required(dtt.datetime)
    comment = Optional(str)


class Pooping(db.Entity):
    time = Required(dtt.datetime)
    comment = Optional(str)


db.bind(provider='sqlite', filename='db.sqlite', create_db=True)
db.generate_mapping(create_tables=True)


###############################################################################
# HELPER FUNCTIONS
###############################################################################
def get_poop_description(previous=None):
    colours = ['πράσινα', 'καφέ', 'κίτρινα', 'μαύρα']
    consistencies = ['υγρά', 'στέρεα', 'σποράκια', 'βλέννα', 'αίμα']
    attributes = colours + consistencies
    if previous is None:
        default_attr = {k: False for k in attributes}
    else:
        default_attr = {k: k in previous for k in attributes}
    win = sg.Window(
        'Κακά',
        layout=(
            [[sg.CBox(k, default=v, key=k)] for k, v in default_attr.items()] +
            [[sg.Text('Άλλο:'), sg.Input(key='comment_text')],
             [sg.Button('OK', key='ok'), sg.Button('Άκυρο', key='cancel')]]))
    event, values = win.Read()
    if event == 'ok':
        desc = values.pop('comment_text', '')
        if len(desc) > 0:
            output_list = [desc] + [k for k, v in values.items() if v]
        else:
            output_list = [k for k, v in values.items() if v]
        output_str = ', '.join(output_list)
    else:
        output_str = None
    win.Close()
    return output_str


@db_session
def get_last_row(table):
    id_ = orm.max(t.id for t in table)
    if id_:
        return table[id_]


@db_session
def is_breastfeeding():
    last_entry = get_last_row(Breastfeeding)
    try:
        is_breastfeeding = last_entry.end_time is None
    except AttributeError:
        is_breastfeeding = False
    return is_breastfeeding


def PopupOffsetWindow(main_string, first_pass_extra):
    first_pass = True
    found_valid = None
    while first_pass or not found_valid:
        offset_win = sg.Window('', layout=[
            [sg.Text(('' if first_pass else first_pass_extra) + main_string)],
            [sg.Input(default_text='0', key='add_new_entry_offset')],
            [sg.Ok()]
        ])
        event, values = offset_win.Read()
        offset_text = values['add_new_entry_offset']
        if offset_text == '':
            offset_text = '0'
        offset = re.findall(r'(\d+)', offset_text)
        if len(offset) == 1:
            offset = [0]
        found_valid = len(offset) == 1
        if found_valid:
            offset = int(offset[0])

        offset_win.Close()
        first_pass = False

    return dtt.timedelta(minutes=offset)


@db_session
def manage_breastfeeding(event, values):
    now = dtt.datetime.now()
    is_left = event == 'left'
    last_entry = get_last_row(Breastfeeding)
    table_is_empty = Breastfeeding.select().count() == 0
    add_new_entry = table_is_empty or not is_breastfeeding()

    if add_new_entry:
        # new feed
        offset = PopupOffsetWindow(
            'Άρχισε πριν πόσα λεπτά (αριθμός ή κενό);',
            'Σφάλμα στην εισαγωγή, μόνο αριθμούς\n')
        Breastfeeding(start_time=now - offset,
                      is_left=is_left,
                      used_shield=True)

    elif is_left == last_entry.is_left:
        # finish ongoing feed
        offset = PopupOffsetWindow(
            'Σταμάτησε πριν πόσα λεπτά (αριθμός ή κενό);',
            'Σφάλμα στην εισαγωγή, μόνο αριθμούς\n')
        last_entry.end_time = now - offset
        last_entry.used_shield = sg.PopupYesNo('Προστασία;')
        comment = sg.PopupGetText('Άλλο σχόλιο;')
        last_entry.comment = '' if comment is None else comment
    elif is_left != last_entry.is_left:
        # cancel ongoing feed
        if sg.PopupYesNo('Ακύρωση;') == 'Yes':
            last_entry.delete()


@db_session
def manage_bottlefeeding():
    now = dtt.datetime.now()
    if not is_breastfeeding():
        succesfully_got_ounces = False
        while not succesfully_got_ounces:
            ounces = sg.PopupGetText('Πόσο ήπιε (oz);')
            if ounces is not None:
                ounces = ounces.replace(',', '.')
                try:
                    ounces = float(ounces)
                    succesfully_got_ounces = True
                except ValueError:
                    pass
        comment = sg.PopupGetText('Άλλο σχόλιο')
        if comment is not None:
            Bottlefeeding(time=now,
                          ounces=ounces,
                          comment=comment)
    else:
        sg.PopupTimed('Ακόμα θηλάζει, δοκιμάστε αφού τελειώσει')


@db_session
def manage_events(event, values):
    now = dtt.datetime.now()

    if event in ['left', 'right']:
        manage_breastfeeding(event, values)
    elif event == 'bottle':
        manage_bottlefeeding()
    elif event == 'peed':
        comment = sg.PopupGetText('Άλλο σχόλιο')
        if comment is not None:
            Peeing(time=now, comment=comment)
    elif event == 'pooped':
        n_pooped = Pooping.select().count()
        if n_pooped > 0:
            prev_comment = Pooping[n_pooped].comment
        else:
            prev_comment = None
        comment = get_poop_description(prev_comment)
        if comment is not None:
            Pooping(time=now, comment=comment)


@db_session
def update_feed():
    # manage timer, left / right buttons
    if is_breastfeeding():
        last_entry = get_last_row(Breastfeeding)
        current_time = (dtt.datetime.now() - last_entry.start_time)
        current_time = int(current_time.total_seconds())
        time_str = '{:02d}:{:02d}'.format(current_time // 60,
                                          current_time % 60)
        left_str = button_str[0] if last_entry.is_left else 'Άκυρο'
        right_str = button_str[1] if not last_entry.is_left else 'Άκυρο'
    else:
        time_str = '00:00.00'
        left_str, right_str = button_str

    return time_str, left_str, right_str


@db_session
def update_last_feed():

    now = dtt.datetime.now()

    last_ended_feed = orm.max(d.end_time for d in Breastfeeding)
    is_left = orm.select(d.is_left for d in Breastfeeding
                         if d.end_time == last_ended_feed).first()
    if last_ended_feed is None:
        last_ended_feed = now
        side_str = '--'
    else:
        side_str = 'ΑΡΙΣΤΕΡΟ' if is_left else 'ΔΕΞΙ'
    dt = (now - last_ended_feed).total_seconds()
    hours = dt // 3600
    minutes = (dt - hours * 3600) // 60
    s = ('Έφαγε από το ' + side_str
         + ' στήθος\n' + f'πριν {hours:02.0f} ώρες {minutes:02.0f} λεπτά')
    return s


###############################################################################
# LAYOUT
###############################################################################
sg.SetOptions(font='Helvetica 14')

button_str = ['Αριστερό', 'Δεξί']
button = [sg.Button(button_str[0], key='left', size=(15, 1)),
          sg.Button(button_str[1], key='right', size=(15, 1))]

main_layout = [
    button + [sg.Button('Μπουκαλάκι', key='bottle', size=(15, 1))],
    [sg.Text('00:00:00', key='timer', size=(15, 1))],
    [sg.Text('', key='last_feed_info', size=(40, 3))],
    [sg.Button('Κατούρησε', key='peed', size=(15, 1))],
    [sg.Button('Κακά', key='pooped', size=(15, 1))]
    [sg.Button('Κλείσιμο', key='close', size=(15, 1))]
]


if __name__ == '__main__':

    if 'Web' in sg.__name__:
        if len(sys.argv) > 1:
            port = int(sys.argv[1])
        main_win = sg.Window('Ιστορικό μωρού', layout=main_layout,
                             web_port=port,
                             web_start_browser=False,
                             # web_multiple_instance=True,
                             disable_close=True
                             )
    else:
        main_win = sg.Window('Ιστορικό μωρού',
                             layout=main_layout)

    while True:
        event, values = main_win.Read(timeout=100)

        if event is None or event == 'close':
            main_win.Close()
            break
        else:
            manage_events(event, values)
            time_str, left_str, right_str = update_feed()
            main_win.Element('timer').Update(time_str)
            main_win.Element('last_feed_info').Update(update_last_feed())
            button[0].Update(left_str)
            button[1].Update(right_str)
