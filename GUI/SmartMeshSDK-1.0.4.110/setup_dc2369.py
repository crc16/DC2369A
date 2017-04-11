'''Setup for SmartMesh SDK python distribution
'''

# Grab the current version from the version file
import os
import sys
import platform

# sys.path.append(os.path.join('libs',         'dustUI'))
# sys.path.append(os.path.join('libs',         'SmartMeshSDK'))
# sys.path.append(os.path.join('app',          'DC2369A'))
# sys.path.append(os.path.join('external_libs','cryptopy'))
sys.path.append('dustUI')
sys.path.append('SmartMeshSDK')
sys.path.append(os.path.join('bin', 'DC2369A'))
sys.path.append('cryptopy')

import sdk_version



# Remove the build and dist folders, a bit slower but ensures that build contains the latest
import shutil
shutil.rmtree("build", ignore_errors=True)
shutil.rmtree("dist", ignore_errors=True)

# TODO: include documentation
# TODO: include functional tests

# Platform-specific initialization
NAME = 'SmartMeshSDK'

datafiles = [('',                       ['DN_LICENSE.txt']),
            ('',                        ['requirements.txt']),
            ('app',                     ['bin/logging.conf']),
            ('dustUI',                  ['dustUI/dust.ico']),]
# includes = []
# excludes = ['_gtkagg', '_tkagg', 'bsddb', 'curses', 'pywin.debugger',
#             'pywin.debugger.dbgcon', 'pywin.dialogs', 'tcl',
#             'pydoc', 'doctest', 'test', 'sqlite3'
#             ]
packages = []
dll_excludes = ['MSVCP90.dll', 'w9xpopen.exe']
# dll_excludes = ['MSVCP90.dll', 'w9xpopen.exe','libgdk-win32-2.0-0.dll', 'libgobject-2.0-0.dll', 
#                 #'tcl84.dll','tk84.dll'
#                 ]
icon_resources = [(1, 'dustUI\dust.ico')]
bitmap_resources = []
other_resources = []

# add the mpl mpl-data folder and rc file
import matplotlib
datafiles += matplotlib.get_py2exe_datafiles()



if platform.system() in ['Darwin']:
    # use setuptools on OS X
    from setuptools import setup
    import py2app

    # use a different name because we're only building one application
    NAME = 'DC2369A'

    platform_setup_options = {
        'app': [os.path.join('bin', 'DC2369A', 'DC2369A.py')],
        'options': { 
            'py2app': {'argv_emulation': True}
        },
        'setup_requires': ['py2app'],
    }

elif platform.system() in ['Windows']:
    # imports for Windows
    # use distutils because it's easier to specify what's included
    from distutils.core import setup
    try:
        import py2exe
    except ImportError:
        pass

    platform_setup_options = {
        #py2exe parameters
        'console': [
            {'script': os.path.join('bin', 'DC2369A', 'DC2369A.py'),
              },
        ],
        'windows': [
            {'script': os.path.join('bin', 'DC2369A', 'DC2369A.py'),
            'icon_resources': icon_resources,},        
        ],
        'options': {
            'py2exe': {
                'compressed': 2,
                'optimize': 2,
                #'includes': includes,
                #'excludes': excludes,
                'packages': packages,
                'dll_excludes': dll_excludes,
                'bundle_files': 1, 
            },
        },
        'zipfile': None,
    }

else:
    # use distutils because it's easier to specify what's included
    from distutils.core import setup
    platform_setup_options = {}


setup(
    name           = NAME,
    version        = '.'.join([str(v) for v in sdk_version.VERSION]),
    scripts        = [
        'bin/DC2369A/DC2369A.py',
    ],
    # TODO: is there an easier way to include packages recursively? 
    # maybe find_packages? 
    packages       = [
        'cryptopy',
        'cryptopy.crypto',
        'cryptopy.crypto.cipher',
        'cryptopy.crypto.entropy',
        'cryptopy.crypto.hash',
        'cryptopy.crypto.keyedHash',
        'cryptopy.crypto.passwords',
        'cryptopy.fmath',
        'dustUI',
        'SmartMeshSDK',
        'SmartMeshSDK.ApiDefinition',
        'SmartMeshSDK.IpMgrConnectorMux',
        'SmartMeshSDK.IpMgrConnectorSerial',
        'SmartMeshSDK.IpMoteConnector',        
        'SmartMeshSDK.HartMgrConnector',        
        'SmartMeshSDK.HartMoteConnector',
        'SmartMeshSDK.protocols',
        'SmartMeshSDK.protocols.DC2369AConverters',
        'SmartMeshSDK.protocols.oap',
        'SmartMeshSDK.protocols.otap',
        'SmartMeshSDK.SerialConnector',
        # application-specific packages
        'DC2369A',
    ],
    package_dir    = {
        '':             '.',
        # application-specific packages
        'DC2369A':    'bin/DC2369A',
    },
    data_files     = datafiles,
    # url          =
    author         = 'Linear Technology',
    author_email   = "dust-support@linear.com",
    license        = 'see DN_LICENSE.txt',
    
    # platform-specific options
    **platform_setup_options
)

#clean up directory
shutil.rmtree("build", ignore_errors=True)




#     # py2exe parameters
#     #console        = [
#      #   {'script': os.path.join('bin', 'InstallTest', 'InstallTest.py'),},
#    #],
#     windows        = [
#         {'script': os.path.join('bin', 'DC2369A', 'DC2369A.py'),
#          'icon_resources': icon_resources,
# },
#     ],
#     zipfile        = None,
#     options        = {
#         'py2exe': {
#             #'compressed': 2,
#             #'optimize': 2,
#             #'includes': includes,
#             #'excludes': excludes,
#             #'packages': packages,
#             'dll_excludes': dll_excludes,
#             'bundle_files': 1, 
#         },
#     },
# )
