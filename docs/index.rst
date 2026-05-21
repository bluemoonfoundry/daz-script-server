dazpy — DAZ Studio Python SDK
==============================

**Version** |release|

**dazpy** is a Python SDK for `DAZ Studio Script Server
<https://github.com/bluemoonfoundry/daz-script-server>`_.  It lets you
connect to a running DAZ Studio instance, execute DazScript code, and
manipulate the scene through a type-safe Python API.

.. code-block:: python

   from dazpy import DazClient, DazScene

   scene  = DazScene()
   figure = scene.find_skeleton("Genesis 9")
   figure.find_bone("rForeArm").set_local_rotation(0, 0, 45)

.. toctree::
   :maxdepth: 2
   :caption: Contents

   quickstart
   api/index

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
