#!/usr/bin/env python3
# -*- coding:utf-8 -*-
#
# Polychromatic is free software: you can redistribute it and/or modify
# it under the temms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Polychromatic is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Polychromatic. If not, see <http://www.gnu.org/licenses/>.
#
# Copyright (C) 2015-2016 Luke Horwell <lukehorwell37+code@gmail.com>
#               2015-2016 Terry Cain <terry@terrys-home.co.uk>

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('WebKit2', '4.0')
import os
import sys
import signal
import json
from gi.repository import Gtk, Gdk, WebKit2
import razer.daemon_dbus
import razer.keyboard
import polychromatic.preferences
import polychromatic.profiles

# Where is the application being ran?
if os.path.exists(os.path.abspath(os.path.join(os.path.dirname(__file__), 'data/'))):
    LOCATION_DATA = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data/'))
elif os.path.exists('/usr/share/polychromatic/data/'):
    LOCATION_DATA = '/usr/share/polychromatic/data/'
else:
    print('Could not source the data directory!')
    exit(1)

class ChromaController(object):
    ##################################################
    # Page Switcher
    ##################################################
    def show_menu(self, page):
        self.current_page = page
        print("Opening page '" + page + "'")

        # Hide all footer buttons
        for element in ['retry', 'edit-save', 'edit-preview', 'cancel', 'close-window', 'pref-open', 'pref-save']:
            self.update_page('#'+element, 'hide')

        if page == 'menu':
            self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, 'menu.html'))

        elif page == 'profile_editor':
            self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, 'profile_editor.html'))

        elif page == 'preferences':
            self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, 'preferences.html'))

        elif page == 'devices':
            self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, 'devices.html'))
        else:
            print("Unknown menu '" + page + "'!")

    ##################################################
    # Page Initialization
    ##################################################
    def page_loaded(self):
        print('Running page post-actions for "' + self.current_page + '"...')

        if self.current_page == 'menu':
            self.webkit.run_javascript('instantProfileSwitch = false;') # Unimplemented instant profile change option.
            self.update_page('#profiles-activate', 'show')
            self.refresh_profiles_list()

            # If there are multiple devices on the system, show the "switch" button.
            if self.multi_device_present:
                self.update_page('#multi-device-switcher', 'show')

            # Tell JavaScript whether live profile switching is enabled.
            if self.preferences.get_pref('chroma_editor', 'live_switch') == 'true':
                self.webkit.run_javascript('live_switch = true;')
                self.update_page('#profiles-activate', 'hide')
            else:
                self.webkit.run_javascript('live_switch = false;')

            # Set preview colours with ones from memory.
            p_red = self.primary_rgb_values[0]
            p_green = self.primary_rgb_values[1]
            p_blue = self.primary_rgb_values[2]

            s_red = self.secondary_rgb_values[0]
            s_green = self.secondary_rgb_values[1]
            s_blue = self.secondary_rgb_values[2]

            self.update_page('#rgb_primary_preview', 'css', 'background-color', 'rgba(' + str(p_red) + ',' + str(p_green) + ',' + str(p_blue) + ',1.0)')
            self.update_page('#rgb_secondary_preview', 'css', 'background-color', 'rgba(' + str(s_red) + ',' + str(s_green) + ',' + str(s_blue) + ',1.0)')


        elif self.current_page == 'profile_editor':
            js_exec = WebkitJavaScriptExecutor(self.webkit)
            kb_callback = WebkitJavaScriptExecutor(None, wrapper="keyboard_obj.load(function(){{{0}}});")


            js_exec << 'change_header("Edit ' + self.open_this_profile + '")'

            kb_callback << "keyboard_obj.set_layout(\"kb-" + self.kb_layout + "\")"

            # Load profile into keyboard.
            profile_name = self.open_this_profile
            self.profiles.set_active_profile(profile_name)
            if self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                self.profiles.activate_profile_from_memory()
            self.profiles.get_active_profile().backup_configuration()

            for pos_y, row in enumerate(self.profiles.get_profile(profile_name).get_rows_raw()):
                for pos_x, rgb in enumerate(row):
                    js_string = "keyboard_obj.set_key_colour({0},{1},\"#{2:02X}{3:02X}{4:02X}\")".format(pos_y, pos_x, rgb.red, rgb.green, rgb.blue)
                    kb_callback << js_string

            # IF BLACKWIDOW ULTIMATE < 2016
            # OR BLACKWIDOW CHROMA
            # disable space key and FN
            kb_callback << "keyboard_obj.disable_key(5,7)"
            kb_callback << "keyboard_obj.disable_key(5,12)"
            # Hide preview button if live previewing is enabled.
            if self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                kb_callback << '$("#edit-preview").hide();'


            kb_callback << "$(\"#cancel\").attr({onclick: \"cmd('cancel-changes?"+ self.cancel_changes + "?" + profile_name + "')\"})"

            js_exec << kb_callback
            js_exec.exec()

        elif self.current_page == 'preferences':
            # Populate start-up profiles list.
            self.refresh_profiles_list()

            # Set checkboxes
            for setting in ['live_switch','live_preview','activate_on_save']:
                if (self.preferences.pref_data['chroma_editor'][setting] == 'true'):
                    self.update_page('#'+setting, 'prop', 'checked', 'true')

            # Fetch settings for tray/start-up settings.
            tray_icon_type = self.preferences.get_pref('tray_applet', 'icon_type', 'system')
            tray_icon_path = self.preferences.get_pref('tray_applet', 'icon_path', '')
            start_enabled = self.preferences.get_pref('startup', 'enabled', 'false')
            start_effect = self.preferences.get_pref('startup', 'start_effect', None)
            start_profile = self.preferences.get_pref('startup', 'start_profile', None)
            start_brightness = int(self.preferences.get_pref('startup', 'start_brightness', 0))
            start_macro = self.preferences.get_pref('startup', 'start_macro', 'false')

            # Set 'values' for textboxes and dropdowns.
            self.update_page('#tray-'+tray_icon_type, 'prop', 'checked', 'true')
            self.update_page('#tray-icon-path', 'val', tray_icon_path)
            self.update_page('#start-effect-dropdown', 'val', start_effect)
            self.update_page('#profiles-list', 'val', start_profile)
            self.update_page('#start-brightness', 'val', str(start_brightness))

            if start_macro == 'true':
                self.update_page('#start-macro', 'prop', 'checked', 'true')

            # Hide/Show UI elements
            if start_enabled == 'true':
                self.update_page('#startup-enabled', 'prop', 'checked', 'true')
                self.update_page('#startup-options', 'show')

            if start_effect == 'profile':
                self.update_page('#start-profile', 'show')
            else:
                self.update_page('#start-profile', 'hide')

            if start_brightness == 0:
                self.update_page('#start-brightness-text', 'html', "No Change")
            else:
                self.update_page('#start-brightness-text', 'html', str(int((start_brightness * 100) / 255 )) + '%')

            # Get default 'preferred' colours.
            self.start_p_red =   self.preferences.get_pref('primary_colors', 'red', 0)
            self.start_p_green = self.preferences.get_pref('primary_colors', 'green', 255)
            self.start_p_blue =  self.preferences.get_pref('primary_colors', 'blue', 0)

            self.start_s_red =   self.preferences.get_pref('secondary_colors', 'red', 255)
            self.start_s_green = self.preferences.get_pref('secondary_colors', 'green', 0)
            self.start_s_blue =  self.preferences.get_pref('secondary_colors', 'blue', 0)

            self.update_page('#rgb_start_primary_preview', 'css', 'background-color', 'rgba(' + str(self.start_p_red) + ',' + str(self.start_p_green) + ',' + str(self.start_p_blue) + ',1.0)')
            self.update_page('#rgb_start_secondary_preview', 'css', 'background-color', 'rgba(' + str(self.start_s_red) + ',' + str(self.start_s_green) + ',' + str(self.start_s_blue) + ',1.0)')

        elif self.current_page == 'controller_devices':
            self.detect_devices()

        else:
            print('No post actions necessary.')


    ##################################################
    # Reusable Page Functions
    ##################################################
    def refresh_profiles_list(self):
        self.update_page('#profiles-list', 'html' , '')
        profiles = list(self.profiles.get_profiles())
        profiles.sort()
        for profile in profiles:
            self.update_page('#profiles-list', 'append', '<option value="'+profile+'">'+profile+'</option>')

    ##################################################
    # Commands
    ##################################################
    def process_command(self, command):
        if command == 'quit':
            quit()

        ## Effects & Keyboard Controls
        elif command.startswith('brightness'):
            value = int(command[11:])
            self.daemon.set_brightness(value)

        elif command.startswith('effect'):
            enabled_options = []

            if command == 'effect-none':
                self.current_effect = "none"
                self.daemon.set_effect('none')

            elif command == 'effect-spectrum':
                self.current_effect = "spectrum"
                self.daemon.set_effect('spectrum')

            elif command.startswith('effect-wave'):
                self.current_effect = "wave"
                wave_direction = int(command.split('?')[1])
                self.daemon.set_effect('wave', wave_direction) # ?1 or ?2 for direction
                enabled_options = ['waves']

            elif command.startswith('effect-reactive'):
                self.current_effect = "reactive"
                if command.split('?')[1] == 'auto':
                    # Use the previous effect
                    self.daemon.set_effect('reactive', self.reactive_speed, self.primary_rgb.red, self.primary_rgb.green, self.primary_rgb.blue)
                else:
                    self.reactive_speed = int(command.split('?')[1])
                    self.daemon.set_effect('reactive', self.reactive_speed, self.primary_rgb.red, self.primary_rgb.green, self.primary_rgb.blue)
                enabled_options = ['rgb_primary', 'reactive']

            elif command.startswith('effect-breath'):
                breath_random = int(command.split('?')[1])
                if breath_random == 1:  # Random mode
                    self.current_effect = "breath?random"
                    self.daemon.set_effect('breath', 1)
                    enabled_options = ['breath-select']
                else:
                    self.current_effect = "breath?colours"
                    self.daemon.set_effect('breath',
                                           self.primary_rgb.red, self.primary_rgb.green, self.primary_rgb.blue,
                                           self.secondary_rgb.red, self.secondary_rgb.green, self.secondary_rgb.blue)
                    enabled_options = ['breath-random', 'rgb_primary', 'rgb_secondary']

            elif command == 'effect-static':
                self.current_effect = "static"
                self.daemon.set_effect('static', self.primary_rgb.red, self.primary_rgb.green, self.primary_rgb.blue)
                enabled_options = ['rgb_primary']

            # Fade between options for that effect, should it have been changed.
            if not self.current_effect == self.last_effect:
                # Effect changed, fade out all previous options.
                for element in ['rgb_primary', 'rgb_secondary', 'waves', 'reactive', 'breath-random', 'breath-select']:
                    self.update_page('#'+element, 'fadeOut', 'fast')

                # Fade in desired options for this effect.
                for element in enabled_options:
                    self.webkit.run_javascript("setTimeout(function(){ $('#" + element + "').fadeIn('fast');}, 200)")
            self.last_effect = self.current_effect

        elif command == 'enable-marco-keys':
            self.daemon.marco_keys(True)
            self.update_page('#macro-keys-enable', 'addClass', 'btn-disabled')
            self.update_page('#macro-keys-enable', 'html', "In Use")

        elif command == 'gamemode-enable':
            self.daemon.game_mode(True)
            self.update_page('#game-mode-status', 'html', 'Enabled')
            self.update_page('#game-mode-enable', 'hide')
            self.update_page('#game-mode-disable', 'show')

        elif command == 'gamemode-disable':
            self.daemon.game_mode(False)
            self.update_page('#game-mode-status', 'html' 'Disabled')
            self.update_page('#game-mode-enable', 'show')
            self.update_page('#game-mode-disable', 'hide')

        ## Changing colours for this session.
        elif command.startswith('ask-color'):
            colorseldlg = Gtk.ColorSelectionDialog("Choose a colour")
            colorsel = colorseldlg.get_color_selection()

            if colorseldlg.run() == Gtk.ResponseType.OK:
                color = colorsel.get_current_color()
                red = int(color.red / 256)
                green = int(color.green / 256)
                blue = int(color.blue / 256)
                element = command.split('?')[1]
                command = 'set-color?'+element+'?'+str(red)+'?'+str(green)+'?'+str(blue)
                self.process_command(command)

            colorseldlg.destroy()

        elif command.startswith('set-color'):
            """ Expects 4 parameters separated by '?' in order: element, red, green, blue (RGB = 0-255) """
            update_effects = False
            colors = command.split('set-color?')[1]
            element = colors.split('?')[0]
            red = int(colors.split('?')[1])
            green = int(colors.split('?')[2])
            blue = int(colors.split('?')[3])
            print("Set colour of '{0}' to RGB: {1}, {2}, {3}".format(element, red, green, blue))

            self.update_page('#'+element+'_preview', 'css', 'background-color', 'rgba(' + str(red) + ',' + str(green) + ',' + str(blue) + ',1.0)')
            self.webkit.run_javascript('set_mode("set")')

            if element == 'rgb_primary':    # Primary effect colour
                update_effects = True
                self.primary_rgb.set((red, green, blue))
                self.primary_rgb_values = [red, green, blue]

            elif element == 'rgb_secondary':   # Secondary effect colour (used for Breath mode)
                update_effects = True
                self.secondary_rgb.set((red, green, blue))
                self.secondary_rgb_values = [red, green, blue]

            elif element == 'rgb_tmp':      # Temporary colour while editing profiles.
                rgb_edit_red = red
                rgb_edit_green = green
                rgb_edit_blue = blue

            elif element == 'rgb_start_primary':  # Starting primary colour specified in Preferences.
                self.start_p_red =   red
                self.start_p_green = green
                self.start_p_blue =  blue

            elif element == 'rgb_start_secondary':  # Starting secondary colour specified in Preferences.
                self.start_s_red =   red
                self.start_s_green = green
                self.start_s_blue =  blue

            # Update static colour effects if currently in use.
            if update_effects:
                if self.current_effect == 'static':
                    self.process_command('effect-static')
                elif self.current_effect == 'breath?colours':
                    self.process_command('effect-breath?0')
                elif self.current_effect == 'reactive':
                    self.process_command('effect-reactive?auto')

        ## Opening different pages
        elif command.startswith('cancel-changes'):
            if command.find('?') > -1:
                command, cancel_type, cancel_args = command.split('?')

                if cancel_type == "new-profile":
                    self.profiles.remove_profile(cancel_args, del_from_fs=False)
                    if self.preferences.get_pref('chroma_editor', 'live_switch') == 'true' or self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                        self.daemon.set_custom_colour(self.old_profile)
                elif cancel_type == "edit-profile":
                    self.profiles.get_active_profile().restore_configuration()
                    if self.preferences.get_pref('chroma_editor', 'live_switch') == 'true' or self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                        self.daemon.set_custom_colour(self.old_profile)

                self.update_page('#cancel', 'attr', '{onclick: \"cmd(\'cancel-changes\')\"}')
            self.show_menu('menu')

        ## Preferences
        elif command == 'pref-open':
            self.show_menu('preferences')

        elif command.startswith('web'):
            print('web')
            target = command.split('web?')[1]
            os.system('xdg-open "' + target + '"')

        elif command.startswith('pref-set?'):
            # pref-set ? <group> ? <setting> ? <value>
            group = command.split('?')[1]
            setting = command.split('?')[2]
            value = command.split('?')[3]
            self.preferences.set_pref(group, setting, value)

        elif command == 'pref-revert':
            print('Reverted preferences.')
            self.preferences.load_pref()
            self.show_menu('menu')

        elif command == 'pref-save':
            # Saves initial colours.
            self.preferences.set_pref('primary_colors', 'red', self.start_p_red)
            self.preferences.set_pref('primary_colors', 'green', self.start_p_green)
            self.preferences.set_pref('primary_colors', 'blue', self.start_p_blue)

            self.preferences.set_pref('secondary_colors', 'red', self.start_s_red)
            self.preferences.set_pref('secondary_colors', 'green', self.start_s_green)
            self.preferences.set_pref('secondary_colors', 'blue', self.start_s_blue)

            # Commits preferences from memory to disk.
            self.preferences.save_pref()

            self.show_menu('menu')

        elif command == 'pref-reset-conf':
            print('User requested to reset configuration.')
            self.preferences.create_default_config()
            self.preferences.load_pref()
            print('Configuration successfully reset.')
            self.show_menu('preferences')

        elif command == 'pref-reset-all':
            print('User requested to reset everything.')
            self.preferences.clear_config()
            print('\nRestarting the application...\n')
            os.execv(__file__, sys.argv)

        ## Profile Editor / Management
        elif command.startswith('profile-edit'):
            self.open_this_profile = command.split('profile-edit?')[1].replace('%20', ' ')
            self.old_profile = self.profiles.get_active_profile()
            self.cancel_changes = 'edit-profile'
            if self.open_this_profile is not None:
                self.show_menu('profile_editor')
            else:
                print('Refusing to open empty filename profile.')

        elif command.startswith('set-key'):
            # Parse position/colour information
            command = command.replace('%20',' ')
            row = int(command.split('?')[1])
            col = int(command.split('?')[2])
            color = command.split('?')[3]

            red = int(color.strip('rgb()').split(',')[0])
            green = int(color.strip('rgb()').split(',')[1])
            blue = int(color.strip('rgb()').split(',')[2])
            rgb = (red, green, blue)

            # Write to memory
            self.profiles.get_active_profile().set_key_colour(row, col, rgb)

            # Live preview (if 'live_preview' is enabled in preferences)
            if self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                self.profiles.activate_profile_from_memory()

        elif command.startswith('clear-key'):
            command = command.replace('%20',' ')
            row = int(command.split('?')[1])
            col = int(command.split('?')[2])

            self.profiles.get_active_profile().reset_key(row, col)

            # Live preview (if 'live_preview' is enabled in preferences)
            if self.preferences.get_pref('chroma_editor', 'live_preview') == 'true':
                self.profiles.activate_profile_from_memory()

        elif command.startswith('profile-activate'):
            command = command.replace('%20',' ')
            profile_name = command.split('profile-activate?')[1]
            self.webkit.run_javascript('set_cursor("html","wait")')
            self.profiles.activate_profile_from_file(profile_name)
            self.update_page('#custom', 'html', 'Profile - ' + profile_name)
            self.update_page('#custom', 'prop', 'checked', 'true')
            self.webkit.run_javascript('set_cursor("html","normal")')

        elif command == 'profile-preview':
            self.profiles.activate_profile_from_memory()

        elif command.startswith('profile-del'):
            # TODO: Instead of JS-based prompt, use PyGtk or within web page interface?
            profile_name = command.split('?')[1].replace('%20', ' ')

            if len(profile_name) > 0:
                self.profiles.remove_profile(profile_name)

                print('Forcing refresh of profiles list...')
                self.refresh_profiles_list()

        elif command.startswith('profile-new'):
            # TODO: Instead of JS-based prompt, use PyGtk or within web page interface?
            profile_name = command.split('?')[1].replace('%20', ' ')

            self.cancel_changes = 'new-profile'
            self.old_profile = self.profiles.get_active_profile()
            self.open_this_profile = profile_name
            self.profiles.new_profile(profile_name)
            self.show_menu('profile_editor')


        elif command == 'profile-save':
            profile_name = self.profiles.get_active_profile_name()
            print('Saving profile "{0}" ...'.format(profile_name))
            self.profiles.save_profile(profile_name)
            print('Saved "{0}".'.format(profile_name))
            self.show_menu('menu')

            if self.preferences.get_pref('chroma_editor', 'activate_on_save') == 'true':
                self.profiles.activate_profile_from_file(self.profiles.get_active_profile_name())

        ## Miscellaneous
        elif command == 'open-config-folder':
            os.system('xdg-open "' + self.preferences.SAVE_ROOT + '"')

        ## Multi-device Management
        elif command.startswith('set-device?'):
            serial = command.split('?')[1]
            self.set_device(serial)

        elif command == 'rescan-devices':
            self.update_page('#detected-devices tr', 'remove')
            self.detect_devices()

        elif command == 'change-device':
            self.show_menu('controller_devices')

        else:
            print("         ... unimplemented!")

    def update_page(self, element, function, parm1=None, parm2=None):
        """ Runs a JavaScript jQuery function on the page,
            ensuring correctly parsed quotes. """
        if parm1 and parm2:
            self.webkit.run_javascript('$("' + element + '").' + function + "('" + parm1.replace("'", '\\\'') + "', '" + parm2.replace("'", '\\\'') + "')")
        if parm1:
            self.webkit.run_javascript('$("' + element + '").' + function + "('" + parm1.replace("'", '\\\'') + "')")
        else:
            self.webkit.run_javascript('$("' + element + '").' + function + '()')


    ##################################################
    # Multi-device support
    ##################################################
    def detect_devices(self):
        # FIXME: Only UI frontend implemented.
        print('fixme:ChromaController.detect_devices')

        # TODO:
        #   -  Program will detect all connected Razer devices and add them to the 'devices' table using JS function.
        #   -  If only one device is avaliable (such as only having one Chroma Keyboard), then automatically open that config page.

        # FIXME: Just a placebo...
        serial = self.daemon.get_serial_number()
        hardware_type = 'blackwidow_chroma'
        self.multi_device_present = True
        print('Found "{0}" (S/N: {1}).'.format(hardware_type, serial))
        self.webkit.run_javascript('add_device("' + serial + '", "' + hardware_type + '")')

        # If this is the only Razer device that can be configured, skip the screen.
        if not self.multi_device_present:
            if hardware_type == 'blackwidow_chroma':
                self.show_menu('menu')

    def set_device(self, serial):
        print('fixme:ChromaController.set_device')
        # TODO:
        #   -  Program knows that this is the 'active' device for configuration.
        #   -  Changes the page based on the type of device.


        serial = self.daemon.get_serial_number()
        hardware_type = 'blackwidow_chroma'
        print('Configuring "{0}" (S/N: {1})".'.format(hardware_type, serial))

        # Open the relevant configuration menu for the selected device.
        if hardware_type == 'blackwidow_chroma' :
            self.current_page = 'menu'
            self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, 'menu.html'))


    ##################################################
    # Application Initialization
    ##################################################
    def __init__(self):
        """
        Initialise the class
        """
        w = Gtk.Window(title="Chroma Driver Configuration")
        w.set_wmclass('razer_bcd_utility', 'razer_bcd_utility')
        w.set_position(Gtk.WindowPosition.CENTER)
        w.set_size_request(1000, 600)
        w.set_resizable(False)
        try:
            w.set_icon_from_file(os.path.join(LOCATION_DATA, 'img/app-icon.svg'))
        except:
            w.set_icon_from_file('/usr/share/icons/hicolor/scalable/apps/polychromatic.svg')
        w.connect("delete-event", Gtk.main_quit)

        if not os.path.exists(LOCATION_DATA):
            print('Data folder is missing. Exiting.')
            sys.exit(1)

        # Initialize Preferences
        self.preferences = polychromatic.preferences.ChromaPreferences()

        # Set up the daemon
        try:
            # Connect to the DBUS
            self.daemon = razer.daemon_dbus.DaemonInterface()

            # Initialize Profiles
            self.profiles = polychromatic.profiles.ChromaProfiles(self.daemon)

            # Load devices page normally.
            #~ self.current_page = 'controller_devices' # TODO: Multi-device not yet supported.
            self.current_page = 'menu'
            self.multi_device_present = False

            # "Globals"
            self.kb_layout = razer.keyboard.get_keyboard_layout()
            self.reactive_speed = 1
            self.primary_rgb = razer.keyboard.RGB(0, 255, 0)
            self.secondary_rgb = razer.keyboard.RGB(0, 0, 255)
            self.current_effect = 'custom'
            self.last_effect = 'unknown'
            self.open_this_profile = None

            # Set preferred colours
            p_red = self.preferences.get_pref('primary_colors', 'red', 0)
            p_green = self.preferences.get_pref('primary_colors', 'green', 255)
            p_blue = self.preferences.get_pref('primary_colors', 'blue', 0)
            s_red = self.preferences.get_pref('secondary_colors', 'red', 255)
            s_green = self.preferences.get_pref('secondary_colors', 'green', 0)
            s_blue = self.preferences.get_pref('secondary_colors', 'blue', 0)

            self.primary_rgb_values = [p_red, p_green, p_blue]
            self.primary_rgb = razer.keyboard.RGB(p_red, p_green, p_blue)

            self.secondary_rgb_values = [s_red, s_green, s_blue]
            self.secondary_rgb = razer.keyboard.RGB(s_red, s_green, s_blue)

        except Exception as e:
            # Load an error page instead.
            print('There was a problem initializing the application or DBUS.')
            self.current_page = 'error'
            print('Exception: ', e)


        # Create WebKit Container
        self.webkit = WebKit2.WebView()

        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.webkit)

        # Build an auto expanding box and add our scrolled window
        b = Gtk.VBox(homogeneous=False, spacing=0)
        b.pack_start(sw, expand=True, fill=True, padding=0)
        w.add(b)

        # Post-actions after pages fully load.
        self.webkit.connect('load-changed', self.load_changed_cb)
        self.webkit.connect('notify::title', self.title_changed_cb)
        self.webkit.connect('context-menu', self.context_menu_cb)

        # Allows Keyboard SVGs to load.
        self.webkit.get_settings().set_property('allow-file-access-from-file-urls', 1)

        # Load the starting page
        self.webkit.load_uri('file://' + os.path.join(LOCATION_DATA, self.current_page + '.html'))

        # Show the window.
        w.show_all()
        Gtk.main()

    def title_changed_cb(self, view, frame):
        title = self.webkit.get_title()
        print('[Debug] Command: ' + title)
        self.process_command(title)

    def load_changed_cb(self, view, frame):
        uri = str(self.webkit.get_uri())
        if not self.webkit.is_loading():
            self.current_page = uri.rsplit('/', 1)[1].split('.html')[0]
            print('[Debug] Page: ' + self.current_page)
            self.page_loaded()

    def context_menu_cb(self, view, menu, event, htr, user_data=None):
        # Disable context menu.
        return True



class WebkitJavaScriptExecutor(object):
    """
    Simple class to execute scripts
    """
    def __init__(self, webkit, script=None, wrapper=None):
        if wrapper is not None:
            self.wrapper = wrapper
        else:
            self.wrapper = "$(document).ready(function(){{{0}}});"
        self.lines = []
        self.webkit = webkit

        if script is not None:
            self.add(script)

    def add(self, line):
        """
        Adds a line to the collection

        :param line: Line to execute
        :type line: str

        :return: Returns a copy of the object
        :rtype: WebkitJavaScriptExecutor
        """
        line = str(line)

        if line.endswith(';'):
            self.lines.append(line)
        else:
            self.lines.append(line + ';')

        return self

    def exec(self):
        payload = str(self)
        self.webkit.run_javascript(payload)

    def __lshift__(self, other):
        self.add(other)

        return self

    def __str__(self):
        lines = '\n' + '\n'.join(self.lines) + '\n'
        result = self.wrapper.format(lines)
        return result



if __name__ == "__main__":
    # Kill the process when CTRL+C'd.
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    ChromaController()
