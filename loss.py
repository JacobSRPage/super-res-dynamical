import jax.numpy as jnp
from typing import Callable

def mse_vel_and_vort(
    vel_true: jnp.ndarray,
    vel_pred: jnp.ndarray,
    vel_to_vort_fn: Callable[[jnp.ndarray], jnp.ndarray]
  ):
  vort_pred = vel_to_vort_fn(vel_pred[:, jnp.newaxis, ...])[:,0,...]
  vort_true = vel_to_vort_fn(vel_true[:, jnp.newaxis, ...])[:,0,...]

  vel_error = (vel_pred - vel_true) ** 2
  vort_error = (vort_pred - vort_true) ** 2
  return 0.5 * jnp.mean(vel_error) + 0.5 * jnp.mean(vort_error)

def mse_and_traj(
    vort_true: jnp.ndarray, 
    vort_pred: jnp.ndarray, 
    trajectory_rollout_fn: Callable[[jnp.ndarray], jnp.ndarray],
    alpha: float = 0.5
    ):
  """ Trajectory fn expects real input and gives real output (i.e. fields in physical space)"""
  squared_errors_recon = (vort_true - vort_pred) ** 2

  # NB vort has been normalized by vort_max for prediction
  true_traj = trajectory_rollout_fn(vort_true)
  pred_traj = trajectory_rollout_fn(vort_pred)
  squared_errors_traj = (true_traj - pred_traj) ** 2
  return alpha * jnp.mean(squared_errors_recon) + (1. - alpha) * jnp.mean(squared_errors_traj)

def mse_and_traj_coarse(
    vort_true: jnp.ndarray, 
    vort_pred: jnp.ndarray, 
    trajectory_rollout_fn: Callable[[jnp.ndarray], jnp.ndarray],
    pooling_fn: Callable[[jnp.ndarray], jnp.ndarray],
    alpha: float = 0.5
    ):
  """ Trajectory fn expects real input and gives real output (i.e. fields in physical space)"""
  # squared_errors_recon = (vort_true - vort_pred) ** 2
  squared_errors_recon = (pooling_fn(vort_true[:, jnp.newaxis, ...]) - pooling_fn(vort_pred[:, jnp.newaxis, ...])) ** 2

  # NB vort has been normalized by vort_max for prediction
  true_traj = trajectory_rollout_fn(vort_true)
  pred_traj = trajectory_rollout_fn(vort_pred)
  squared_errors_traj = (pooling_fn(true_traj) - 
                         pooling_fn(pred_traj)) ** 2
  return alpha * jnp.mean(squared_errors_recon) + (1. - alpha) * jnp.mean(squared_errors_traj)

def mse_and_traj_vel(
    vel_true: jnp.ndarray, 
    vel_pred: jnp.ndarray, 
    trajectory_rollout_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vel_to_vort_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vort_to_vel_fn: Callable[[jnp.ndarray], jnp.ndarray], 
    alpha: float = 0.5
    ):
  """ Trajectory fn expects real input and gives real output (i.e. fields in physical space)"""
  squared_errors_recon = (vel_true - vel_pred) ** 2

  # (1) need to first convert vel to vort
  vort_pred = vel_to_vort_fn(vel_pred[:, jnp.newaxis, ...])[:,0,...]
  vort_true = vel_to_vort_fn(vel_true[:, jnp.newaxis, ...])[:,0,...]

  # (2) Unroll
  true_traj = trajectory_rollout_fn(vort_true)
  pred_traj = trajectory_rollout_fn(vort_pred)

  # (3) back to vel -- note dimensionality mismatch, now for trajs
  vel_true_traj = vort_to_vel_fn(true_traj)
  vel_pred_traj = vort_to_vel_fn(pred_traj)

  squared_errors_traj = (vel_true_traj - vel_pred_traj) ** 2
  return alpha * jnp.mean(squared_errors_recon) + (1. - alpha) * jnp.mean(squared_errors_traj)

def mse_and_traj_vel_coarse(
    vel_true: jnp.ndarray, 
    vel_pred: jnp.ndarray, 
    trajectory_rollout_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vel_to_vort_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vort_to_vel_fn: Callable[[jnp.ndarray], jnp.ndarray], 
    pooling_fn: Callable[[jnp.ndarray], jnp.ndarray],
    alpha: float = 0.5
    ):
  """ Trajectory fn expects real input and gives real output (i.e. fields in physical space)"""
  squared_errors_recon = (pooling_fn(vel_true[:, jnp.newaxis, ...]) - 
                          pooling_fn(vel_pred[:, jnp.newaxis, ...])) ** 2

  # (1) need to first convert vel to vort
  vort_pred = vel_to_vort_fn(vel_pred[:, jnp.newaxis, ...])[:,0,...]
  vort_true = vel_to_vort_fn(vel_true[:, jnp.newaxis, ...])[:,0,...]

  # (2) Unroll
  true_traj = trajectory_rollout_fn(vort_true)
  pred_traj = trajectory_rollout_fn(vort_pred)

  # (3) back to vel -- note dimensionality mismatch, now for trajs
  vel_true_traj = vort_to_vel_fn(true_traj)
  vel_pred_traj = vort_to_vel_fn(pred_traj)

  squared_errors_traj = (pooling_fn(vel_true_traj) - 
                         pooling_fn(vel_pred_traj)) ** 2
  return alpha * jnp.mean(squared_errors_recon) + (1. - alpha) * jnp.mean(squared_errors_traj)


# need some trickery so that y_true and y_pred appear to have the same shape ... 
# fudge to work with keras model.fit method (TODO JP custom training loop)
def traj_vel_coarse_noise(
    vel_true_traj: jnp.ndarray, 
    vel_pred_traj: jnp.ndarray, # note has the shape of a trajectory, but really is copies of single snapshot
    trajectory_rollout_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vel_to_vort_fn: Callable[[jnp.ndarray], jnp.ndarray],
    vort_to_vel_fn: Callable[[jnp.ndarray], jnp.ndarray], 
    pooling_fn: Callable[[jnp.ndarray], jnp.ndarray],
    ):
  """  Loads in full trajectories (with noise) for comparison 
       vel_true_traj.shape = (batch_size, time, Nx, Ny, 2)
       vel_pred.shape = (batch_size, Nx, Ny, 2) """
  # deal with awkward data-structure: extract single snapshot 
  vel_pred = vel_pred_traj[:, 0, ...]
  vel_true_traj_coarse = pooling_fn(vel_true_traj)
  
  # (1) need to first convert vel to vort
  vort_pred = vel_to_vort_fn(vel_pred[:, jnp.newaxis, ...])[:,0,...]

  # (2) Unroll
  pred_traj = trajectory_rollout_fn(vort_pred)

  # (3) back to vel -- note dimensionality mismatch, now for trajs
  vel_pred_traj = vort_to_vel_fn(pred_traj)
  vel_pred_traj_coarse = pooling_fn(vel_pred_traj)

  squared_errors_traj = (vel_true_traj_coarse - 
                         vel_pred_traj_coarse) ** 2
  return jnp.mean(squared_errors_traj)
