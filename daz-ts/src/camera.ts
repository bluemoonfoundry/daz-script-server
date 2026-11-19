import { DazNode } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzCamera` node. Extends `DazNode` with optical and
 * image-sensor properties.
 */
export class DazCamera extends DazNode {
  /** Focal length in millimetres (read/write, direct `.focalLength` field access). */
  async focalLength(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.focalLength;"))).value as number | null;
  }

  async setFocalLength(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.focalLength = ${ScriptBuilder.serializeArg(value)};`));
  }

  /** Field of view in degrees (read-only; derived from focal length). */
  async fov(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.getFieldOfView();"))).value as number | null;
  }

  /** Whether depth-of-field simulation is enabled (read/write). */
  async depthOfField(): Promise<boolean | null> {
    return (await this.getProperty("Depth of Field")) as boolean | null;
  }

  async setDepthOfField(value: boolean): Promise<void> {
    await this.setProperty("Depth of Field", value);
  }

  /** Horizontal lens shift in millimetres (read/write). */
  async lensShiftX(): Promise<number | null> {
    return (await this.getProperty("Lens Shift X (mm)")) as number | null;
  }

  async setLensShiftX(value: number): Promise<void> {
    await this.setProperty("Lens Shift X (mm)", value);
  }

  /** Vertical lens shift in millimetres (read/write). */
  async lensShiftY(): Promise<number | null> {
    return (await this.getProperty("Lens Shift Y (mm)")) as number | null;
  }

  async setLensShiftY(value: number): Promise<void> {
    await this.setProperty("Lens Shift Y (mm)", value);
  }

  /** Aperture / f-stop — controls depth-of-field blur intensity (read/write). */
  async fStop(): Promise<number | null> {
    return (await this.getProperty("F/Stop")) as number | null;
  }

  async setFStop(value: number): Promise<void> {
    await this.setProperty("F/Stop", value);
  }

  /** Bokeh blade count (read/write); `0` = circular bokeh, 3+ = polygonal. */
  async apertureBlades(): Promise<number | null> {
    return (await this.getProperty("Aperture Blades")) as number | null;
  }

  async setApertureBlades(value: number): Promise<void> {
    await this.setProperty("Aperture Blades", Math.trunc(value));
  }

  /** Bokeh polygon rotation angle in degrees (read/write). */
  async apertureBladeRotation(): Promise<number | null> {
    return (await this.getProperty("Aperture Blade Rotation")) as number | null;
  }

  async setApertureBladeRotation(value: number): Promise<void> {
    await this.setProperty("Aperture Blade Rotation", value);
  }

  /** Sensor / film-gate width in millimetres (read-only). */
  async frameWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.frameWidth;"))).value as number | null;
  }

  /** Distance to the focus plane (read/write). */
  async focalDistance(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.focalDistance;"))).value as number | null;
  }

  async setFocalDistance(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.focalDistance = ${ScriptBuilder.serializeArg(value)};`));
  }

  /** Render aspect ratio width component (read/write). */
  async aspectWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.aspectWidth;"))).value as number | null;
  }

  async setAspectWidth(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.aspectWidth = ${ScriptBuilder.serializeArg(value)};`));
  }

  /** Render aspect ratio height component (read/write). */
  async aspectHeight(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.aspectHeight;"))).value as number | null;
  }

  async setAspectHeight(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.aspectHeight = ${ScriptBuilder.serializeArg(value)};`));
  }

  /** Render image width in pixels (read/write). */
  async pixelsWidth(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.pixelsWidth;"))).value as number | null;
  }

  async setPixelsWidth(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.pixelsWidth = ${ScriptBuilder.serializeArg(Math.trunc(value))};`));
  }

  /** Render image height in pixels (read/write). */
  async pixelsHeight(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.pixelsHeight;"))).value as number | null;
  }

  async setPixelsHeight(value: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.pixelsHeight = ${ScriptBuilder.serializeArg(Math.trunc(value))};`));
  }

  /** Near clipping plane distance (read-only). */
  async nearClippingPlane(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.nearClippingPlane;"))).value as number | null;
  }

  /** Far clipping plane distance (read-only). */
  async farClippingPlane(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.farClippingPlane;"))).value as number | null;
  }

  /** Point the camera at a world-space coordinate. */
  async aimAt(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.aimAt(new DzVec3(${ScriptBuilder.serializeArg(x)}, ${ScriptBuilder.serializeArg(y)}, ${ScriptBuilder.serializeArg(z)}));`
      )
    );
  }

  /** World-space focal point as `{x, y, z}`. */
  async focalPoint(): Promise<{ x: number; y: number; z: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var fp = _node.getFocalPoint(); return {x: fp.x, y: fp.y, z: fp.z};"))
    ).value as { x: number; y: number; z: number } | null;
  }

  /** `true` if this is the active viewport camera. */
  async isViewCamera(): Promise<boolean | null> {
    return (await this.client.execute(this.nodeScript("return _node.isViewCamera();"))).value as boolean | null;
  }
}
