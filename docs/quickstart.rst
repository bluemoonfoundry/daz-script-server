Quick Start
===========

Installation
------------

.. code-block:: bash

   pip install dazpy

dazpy requires Python 3.10+ and a running instance of DAZ Studio with the
**DazScriptServer** plugin loaded (default port ``18811``).

Connecting
----------

.. code-block:: python

   from dazpy import DazClient

   # Auto-loads token from ~/.daz3d/dazscriptserver_token.txt
   client = DazClient()

   # Or supply the token explicitly
   client = DazClient(token="my-secret-token")

   # Custom host / port
   client = DazClient(host="192.168.1.10", port=18811, timeout=60.0)

Verify connectivity::

   print(client.health())
   # {'status': 'ok', 'version': '...'}

Working with the Scene
-----------------------

.. code-block:: python

   from dazpy import DazScene

   scene = DazScene()

   # List all nodes
   for node in scene.nodes():
       print(node.name, node.label)

   # Find a specific figure by its Scene-panel label
   figure = scene.find_skeleton_by_label("Genesis 9")
   print(figure.num_bones(), "bones")

Posing a Figure
---------------

.. code-block:: python

   arm = figure.find_bone("r_forearm")   # Genesis 9 snake_case naming
   arm.set_local_rotation(0, 0, 45)      # 45° on the Z axis

   # Wrap in an undo group
   with scene.undo("Bend arm"):
       arm.set_local_rotation(0, 0, 90)

Working with Morphs
--------------------

.. code-block:: python

   for morph in figure.morphs():
       print(morph.modifier_label, morph.value)

   smile = figure.find_modifier("Smile")
   if smile:
       smile.value = 0.75

Materials
---------

.. code-block:: python

   for mat in figure.materials():
       print(mat.material_name, mat.diffuse_color)

   skin = figure.find_material("1_SkinFace")
   if skin:
       skin.diffuse_color = {"r": 255, "g": 220, "b": 190}

Cameras and Lights
------------------

.. code-block:: python

   cam = scene.cameras()[0]
   cam.focal_length = 85.0
   cam.aim_at(0, 100, 0)

   light = scene.lights()[0]
   light.intensity = 2.0
   light.set_color(255, 240, 200)

Asynchronous / Long-Running Scripts
-------------------------------------

For scripts that may take several seconds, use the async helpers::

   from dazpy import DazClient, execute_long

   client = DazClient()
   result = execute_long(client, "return Scene.getNumNodes();", timeout=30.0)
   print(result.value)

Or manage async requests manually::

   request_id = client.execute_async_submit("return Scene.getNumNodes();")
   data = client.get_request_result(request_id, wait=True, wait_timeout=30)
   print(data["result"])

Geometry Access
---------------

.. code-block:: python

   from dazpy import DazGeometry, NodeIdentifier

   geo = DazGeometry(client, NodeIdentifier("Genesis9"))
   print(geo.vertex_count, "vertices")

   # Paginated full vertex list (avoids large single requests)
   all_verts = geo.vertex_positions_all(chunk_size=2000)

Batch Execution
---------------

Collect multiple reads into one HTTP round-trip::

   from dazpy import Batch

   with Batch(client) as b:
       n_nodes    = b.add(["var n_nodes = Scene.getNumNodes();"])
       n_cameras  = b.add(["var n_cameras = Scene.getNumCameras();"])

   print(n_nodes.value, n_cameras.value)

Error Handling
--------------

.. code-block:: python

   from dazpy import exceptions

   try:
       result = client.execute("return undefinedVariable;")
   except exceptions.ScriptRuntimeError as e:
       print("Script error:", e)
       print(e.diagnostic)   # line-numbered source + error
   except exceptions.ConnectionError:
       print("DAZ Studio is not running")
   except exceptions.AuthenticationError:
       print("Bad token")
