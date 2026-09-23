"""ByteTrack multi-object tracking implementation in pure NumPy and SciPy.

Based on the ByteTrack algorithm (Zhang et al.):
"ByteTrack: Multi-Object Tracking by Associating Every Detection Box"

This implementation uses:
- 8-dimensional Kalman filter for state estimation (position + velocity)
- Two-stage bipartite Hungarian matching via scipy.optimize.linear_sum_assignment
- Zero external C++ or non-standard dependencies.
"""

from enum import IntEnum
from typing import List, Optional, Tuple
import numpy as np
from scipy.optimize import linear_sum_assignment


class TrackState(IntEnum):
    """Lifecycle states of a tracked object."""
    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3


class KalmanFilter:
    """Kalman filter for tracking bounding boxes in image space (x, y, a, h).

    State vector: [x, y, a, h, vx, vy, va, vh]
    - (x, y): center position of the bounding box
    - a: aspect ratio (width / height)
    - h: height of the bounding box
    - (vx, vy, va, vh): respective velocities
    """

    def __init__(self):
        ndim, dt = 4, 1.0

        # Motion model: constant velocity
        self._motion_mat = np.eye(2 * ndim, 2 * ndim, dtype=np.float32)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt

        # Measurement model: observes (x, y, a, h)
        self._update_mat = np.eye(ndim, 2 * ndim, dtype=np.float32)

        # Motion and observation noise scale factors
        self._std_weight_position = 1.0 / 20
        self._std_weight_velocity = 1.0 / 160

    def initiate(self, measurement: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Create track from an unassociated measurement."""
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]

        std = [
            2 * self._std_weight_position * measurement[3],
            2 * self._std_weight_position * measurement[3],
            1e-2,
            2 * self._std_weight_position * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            1e-5,
            10 * self._std_weight_velocity * measurement[3],
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Run Kalman filter prediction step."""
        std_pos = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3],
        ]
        std_vel = [
            self._std_weight_velocity * mean[3],
            self._std_weight_velocity * mean[3],
            1e-5,
            self._std_weight_velocity * mean[3],
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))

        mean = np.dot(self._motion_mat, mean)
        covariance = (
            np.linalg.multi_dot((self._motion_mat, covariance, self._motion_mat.T))
            + motion_cov
        )
        return mean, covariance

    def project(self, mean: np.ndarray, covariance: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Project state distribution to measurement space."""
        std = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-1,
            self._std_weight_position * mean[3],
        ]
        innovation_cov = np.diag(np.square(std))

        mean = np.dot(self._update_mat, mean)
        covariance = (
            np.linalg.multi_dot((self._update_mat, covariance, self._update_mat.T))
            + innovation_cov
        )
        return mean, covariance

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Run Kalman filter correction step given a measurement."""
        projected_mean, projected_cov = self.project(mean, covariance)

        chol_factor, lower = np.linalg.cholesky(projected_cov), True
        kalman_gain = np.linalg.solve(
            chol_factor,
            np.dot(covariance, self._update_mat.T).T,
        ).T
        kalman_gain = np.linalg.solve(chol_factor.T, kalman_gain.T).T

        innovation = measurement - projected_mean
        new_mean = mean + np.dot(innovation, kalman_gain.T)
        new_covariance = covariance - np.linalg.multi_dot(
            (kalman_gain, projected_cov, kalman_gain.T)
        )
        return new_mean, new_covariance


def box_iou(atlbr: np.ndarray, btlbr: np.ndarray) -> np.ndarray:
    """Compute pairwise Intersection over Union (IoU) between two sets of boxes."""
    if len(atlbr) == 0 or len(btlbr) == 0:
        return np.zeros((len(atlbr), len(btlbr)), dtype=np.float32)

    atlbr = np.ascontiguousarray(atlbr, dtype=np.float32)
    btlbr = np.ascontiguousarray(btlbr, dtype=np.float32)

    # Intersection coordinates
    int_x1 = np.maximum(atlbr[:, 0:1], btlbr[:, 0])
    int_y1 = np.maximum(atlbr[:, 1:2], btlbr[:, 1])
    int_x2 = np.minimum(atlbr[:, 2:3], btlbr[:, 2])
    int_y2 = np.minimum(atlbr[:, 3:4], btlbr[:, 3])

    int_w = np.maximum(0.0, int_x2 - int_x1)
    int_h = np.maximum(0.0, int_y2 - int_y1)
    intersection = int_w * int_h

    # Areas
    area_a = (atlbr[:, 2] - atlbr[:, 0]) * (atlbr[:, 3] - atlbr[:, 1])
    area_b = (btlbr[:, 2] - btlbr[:, 0]) * (btlbr[:, 3] - btlbr[:, 1])

    union = area_a[:, None] + area_b[None, :] - intersection
    union = np.maximum(union, 1e-9)

    return intersection / union


def linear_assignment(
    cost_matrix: np.ndarray, threshold: float
) -> Tuple[np.ndarray, List[int], List[int]]:
    """Solve linear assignment problem with Hungarian algorithm and gating threshold."""
    if cost_matrix.size == 0:
        return (
            np.empty((0, 2), dtype=int),
            list(range(cost_matrix.shape[0])),
            list(range(cost_matrix.shape[1])),
        )

    row_indices, col_indices = linear_sum_assignment(cost_matrix)
    matches = []
    unmatched_rows = list(set(range(cost_matrix.shape[0])) - set(row_indices))
    unmatched_cols = list(set(range(cost_matrix.shape[1])) - set(col_indices))

    for r, c in zip(row_indices, col_indices):
        if cost_matrix[r, c] > threshold:
            unmatched_rows.append(r)
            unmatched_cols.append(c)
        else:
            matches.append([r, c])

    matches = np.asarray(matches, dtype=int).reshape(-1, 2) if matches else np.empty((0, 2), dtype=int)
    return matches, sorted(unmatched_rows), sorted(unmatched_cols)


class STrack:
    """Single object tracklet."""

    _count = 0

    def __init__(self, tlwh: np.ndarray, score: float):
        # [x1, y1, w, h]
        self._tlwh = np.asarray(tlwh, dtype=np.float32)
        self.score = float(score)

        self.kalman_filter = KalmanFilter()
        self.mean: Optional[np.ndarray] = None
        self.covariance: Optional[np.ndarray] = None

        self.track_id = 0
        self.state = TrackState.New
        self.is_activated = False

        self.frame_id = 0
        self.start_frame = 0
        self.tracklet_len = 0

    @classmethod
    def reset_counter(cls):
        """Reset global track ID counter."""
        cls._count = 0

    @classmethod
    def next_id(cls) -> int:
        cls._count += 1
        return cls._count

    @property
    def tlwh(self) -> np.ndarray:
        """Get bounding box in [top_left_x, top_left_y, width, height] format."""
        if self.mean is None:
            return self._tlwh.copy()
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    @property
    def tlbr(self) -> np.ndarray:
        """Get bounding box in [x1, y1, x2, y2] format."""
        ret = self.tlwh
        ret[2:] += ret[:2]
        return ret

    def to_xyah(self) -> np.ndarray:
        """Convert [x1, y1, w, h] to [x_center, y_center, aspect_ratio, height]."""
        ret = self._tlwh.copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    def activate(self, kalman_filter: KalmanFilter, frame_id: int):
        """Activate a brand new tracklet."""
        self.kalman_filter = kalman_filter
        self.track_id = self.next_id()
        self.mean, self.covariance = self.kalman_filter.initiate(self.to_xyah())

        self.tracklet_len = 0
        self.state = TrackState.Tracked
        if frame_id == 1:
            self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id

    def re_activate(self, new_track: "STrack", frame_id: int, new_id: bool = False):
        """Re-activate a lost tracklet with new detection."""
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, new_track.to_xyah()
        )
        self.tracklet_len = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = self.next_id()
        self.score = new_track.score

    def update(self, new_track: "STrack", frame_id: int):
        """Update a currently tracked tracklet with new detection."""
        self.frame_id = frame_id
        self.tracklet_len += 1

        new_tlwh = new_track.tlwh
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, new_track.to_xyah()
        )
        self.state = TrackState.Tracked
        self.is_activated = True
        self.score = new_track.score

    def predict(self):
        """Kalman filter prediction step."""
        if self.mean is not None and self.covariance is not None:
            mean_state = self.mean.copy()
            if self.state != TrackState.Tracked:
                mean_state[7] = 0
            self.mean, self.covariance = self.kalman_filter.predict(
                mean_state, self.covariance
            )

    def mark_lost(self):
        self.state = TrackState.Lost

    def mark_removed(self):
        self.state = TrackState.Removed


class BYTETracker:
    """ByteTrack multi-object tracker.

    Associates both high-confidence and low-confidence detections across frames
    to retain tracks through occlusions and motion blur.
    """

    def __init__(
        self,
        track_thresh: float = 0.45,
        match_thresh: float = 0.8,
        track_buffer: int = 30,
        frame_rate: int = 30,
    ):
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.frame_id = 0
        self.max_time_lost = max(2, int(frame_rate / 30.0 * track_buffer))
        self.kalman_filter = KalmanFilter()

        self.tracked_stracks: List[STrack] = []
        self.lost_stracks: List[STrack] = []
        self.removed_stracks: List[STrack] = []

    def reset(self):
        """Reset tracker state and track IDs."""
        self.frame_id = 0
        self.tracked_stracks.clear()
        self.lost_stracks.clear()
        self.removed_stracks.clear()
        STrack.reset_counter()

    def update(self, output_results: np.ndarray) -> List[STrack]:
        """Update tracker with new frame detections.

        Args:
            output_results: Array of shape (N, 5) with [x1, y1, x2, y2, score].

        Returns:
            List of actively tracked STrack objects.
        """
        self.frame_id += 1
        activated_stracks: List[STrack] = []
        refind_stracks: List[STrack] = []
        lost_stracks: List[STrack] = []
        removed_stracks: List[STrack] = []

        if len(output_results) > 0:
            scores = output_results[:, 4]
            bboxes = output_results[:, :4]

            # Convert [x1, y1, x2, y2] -> [x1, y1, w, h]
            tlwhs = np.zeros_like(bboxes)
            tlwhs[:, :2] = bboxes[:, :2]
            tlwhs[:, 2:] = bboxes[:, 2:] - bboxes[:, :2]

            remain_inds = scores >= self.track_thresh
            inds_low = scores < self.track_thresh
            inds_high = remain_inds

            detections = [STrack(tlwh, s) for tlwh, s in zip(tlwhs[inds_high], scores[inds_high])]
            detections_second = [
                STrack(tlwh, s) for tlwh, s in zip(tlwhs[inds_low], scores[inds_low])
            ]
        else:
            detections = []
            detections_second = []

        # Split tracked stracks into confirmed (already activated) and unconfirmed
        unconfirmed: List[STrack] = []
        tracked_stracks: List[STrack] = []
        for track in self.tracked_stracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        # -------------------------------------------------------------
        # Step 1: Predict the new locations of current tracks
        # -------------------------------------------------------------
        strack_pool = tracked_stracks + self.lost_stracks
        for strack in strack_pool:
            strack.predict()

        # -------------------------------------------------------------
        # Step 2: First association (High-score detections vs Active/Lost tracks)
        # -------------------------------------------------------------
        if strack_pool and detections:
            dists = 1.0 - box_iou(
                np.array([s.tlbr for s in strack_pool]),
                np.array([d.tlbr for d in detections]),
            )
            matches, u_track, u_detection = linear_assignment(dists, threshold=self.match_thresh)
        else:
            matches = np.empty((0, 2), dtype=int)
            u_track = list(range(len(strack_pool)))
            u_detection = list(range(len(detections)))

        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = detections[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        # -------------------------------------------------------------
        # Step 3: Second association (Low-score detections vs Unmatched active tracks)
        # -------------------------------------------------------------
        r_tracked_stracks = [
            strack_pool[i]
            for i in u_track
            if strack_pool[i].state == TrackState.Tracked
        ]

        if r_tracked_stracks and detections_second:
            dists = 1.0 - box_iou(
                np.array([s.tlbr for s in r_tracked_stracks]),
                np.array([d.tlbr for d in detections_second]),
            )
            matches, u_track_second, _ = linear_assignment(dists, threshold=0.5)
        else:
            matches = np.empty((0, 2), dtype=int)
            u_track_second = list(range(len(r_tracked_stracks)))

        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = detections_second[idet]
            if track.state == TrackState.Tracked:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        for it in u_track_second:
            track = r_tracked_stracks[it]
            if track.state != TrackState.Lost:
                track.mark_lost()
                lost_stracks.append(track)

        # -------------------------------------------------------------
        # Step 4: Deal with unconfirmed tracks (matches with remaining high-score detections)
        # -------------------------------------------------------------
        detections_remain = [detections[i] for i in u_detection]
        if unconfirmed and detections_remain:
            dists = 1.0 - box_iou(
                np.array([s.tlbr for s in unconfirmed]),
                np.array([d.tlbr for d in detections_remain]),
            )
            matches, u_unconfirmed, u_detection_final = linear_assignment(
                dists, threshold=0.7
            )
        else:
            matches = np.empty((0, 2), dtype=int)
            u_unconfirmed = list(range(len(unconfirmed)))
            u_detection_final = list(range(len(detections_remain)))

        for itracked, idet in matches:
            unconfirmed[itracked].update(detections_remain[idet], self.frame_id)
            activated_stracks.append(unconfirmed[itracked])

        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.mark_removed()
            removed_stracks.append(track)

        # -------------------------------------------------------------
        # Step 5: Initialize new tracks for leftover high-score detections
        # -------------------------------------------------------------
        for inew in u_detection_final:
            track = detections_remain[inew]
            if track.score >= self.track_thresh:
                track.activate(self.kalman_filter, self.frame_id)
                activated_stracks.append(track)

        # -------------------------------------------------------------
        # Step 6: Update tracker lists & remove dead tracks
        # -------------------------------------------------------------
        for track in self.lost_stracks:
            if self.frame_id - track.frame_id > self.max_time_lost:
                track.mark_removed()
                removed_stracks.append(track)

        self.tracked_stracks = [
            t for t in self.tracked_stracks if t.state == TrackState.Tracked
        ]
        self.tracked_stracks = list(
            {t.track_id: t for t in (self.tracked_stracks + activated_stracks + refind_stracks)}.values()
        )

        self.lost_stracks = [
            t for t in self.lost_stracks if t.state == TrackState.Lost
        ]
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = list(
            {t.track_id: t for t in self.lost_stracks if t.track_id not in {ts.track_id for ts in self.tracked_stracks}}.values()
        )
        self.removed_stracks.extend(removed_stracks)

        output_stracks = [
            track
            for track in self.tracked_stracks
            if track.is_activated
        ]

        return output_stracks
