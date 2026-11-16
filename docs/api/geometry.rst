Geometry
========

.. autoclass:: dazpy.DazGeometry
   :members:
   :undoc-members:
   :show-inheritance:

Geometry frames export
----------------------

:meth:`dazpy.DazClient.export_geometry_frames` returns the deformed figure mesh
and bone origins for a list of frames in one native call
(``POST /geometry/frames``).

.. autoclass:: dazpy.GeometryFrames
   :members:

.. autofunction:: dazpy.parse_geometry_frames
