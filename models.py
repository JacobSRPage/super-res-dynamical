""" Attempt to convert old tf keras model to jax backend """
import keras
import keras.backend as K
import keras.ops as kops
from keras.layers import Conv2D, Lambda
from keras.layers import Input, MaxPooling2D, UpSampling2D
from keras.layers import BatchNormalization, Concatenate, Activation

from keras.models import Model
import jax.numpy as jnp

def pad_periodic(x, n_pad_rows=0, n_pad_cols=0):
  """
  Pads the rows and columns of a 4D tensor in a periodic manner.

    Args:
      x (np.ndarray): Input tensor with shape (batch_size, height, width, channels).
      n_pad_x (int): Number of rows to pad.
      n_pad_y (int): Number of columns to pad.

    Returns:
      np.ndarray: Padded tensor with shape (batch_size, height + n_pad_x, width + n_pad_y, channels).
  """
  top_rows = x[:, -n_pad_rows // 2:, :, :]
  bottom_rows = x[:, :n_pad_rows // 2, :, :]
  padded_rows_x = kops.concatenate([top_rows, x, bottom_rows], axis=1)

  left_cols = padded_rows_x[:, :, -n_pad_cols // 2:, :]
  right_cols = padded_rows_x[:, :, :n_pad_cols // 2, :]
  padded_rows_cols_x = kops.concatenate([left_cols, padded_rows_x, right_cols], axis=2)
  return padded_rows_cols_x


def periodic_convolution(x, n_filters, kernel, activation='relu', 
                         strides=(1,1), n_pad_rows=0, n_pad_cols=0):
  """ 
  Applies periodic boundary conditions before convolving an input tensor with a set of filters.

    Args:
        x (np.ndarray): Input tensor with shape (batch_size, height, width, channels).
        n_filters (int): Number of filters to use in the convolution.
        kernel (tuple(int)): Tuple specifying the dimensions of the convolution kernel. Should have length 2.
        activation (str or callable): Activation function to use after the convolution. Defaults to 'relu'.
        strides (tuple(int)): Tuple specifying the strides to use in the convolution. Should have length 2.
        n_pad_rows/cols (int): Number of rows/cols to pad before convolving the tensor.

    Returns:
        np.ndarray: Tensor resulting from the convolution, with shape (batch_size, new_height, new_width, n_filters).
  """
  # shape computation with padding; does not include batch dimension 
  padded_shape = (x.shape[1] + n_pad_rows, x.shape[2] + n_pad_cols, x.shape[-1])

  x_padded = Lambda(pad_periodic, arguments={'n_pad_rows': n_pad_rows, 'n_pad_cols': n_pad_cols},
                    output_shape=padded_shape)(x)
  return Conv2D(n_filters, kernel, activation=activation, padding='valid', strides=strides)(x_padded)


def dense_block_periodic_conv(x, n_blocks, growth_rate,
                              kernel=(1,1), strides=(1,1),
                              n_pad_rows=1, n_pad_cols=1,
                              activation='relu'):
  for j in range(n_blocks):
    xj = BatchNormalization()(x)
    xj = Activation(activation)(xj)
    xj = periodic_convolution(xj, growth_rate, kernel, strides=strides,
                              n_pad_rows=n_pad_rows, n_pad_cols=n_pad_cols)
    x = Concatenate(axis=-1)([x, xj])
  return x


def ae_densenet_v7(Nx, Ny, encoded_dim, return_encoder_decoder=False):
  """ 
  More feature maps, no FC 
  """
  input_vort = Input(shape=(Nx, Ny, 1))
   
  # Dense block (1) -- raw features on full field
  x = periodic_convolution(input_vort, 64, (8,8), strides=(1,1),
                           n_pad_rows=7, n_pad_cols=7, activation='gelu')
  x = dense_block_periodic_conv(x, 3, 32, (8,8), strides=(1,1),
                                n_pad_rows=7, n_pad_cols=7, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = MaxPooling2D((2,2), padding='same')(x)

  # 64 x 64
  x = periodic_convolution(x, 32, (4,4), strides=(1,1),
                           n_pad_rows=3, n_pad_cols=3, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = dense_block_periodic_conv(x, 3, 32, (4,4), strides=(1,1),
                                n_pad_rows=3, n_pad_cols=3, activation='gelu')
  x = MaxPooling2D((2,2), padding='same')(x)

  # 32 x 32
  x = periodic_convolution(x, 32, (4,4), strides=(1,1),
                           n_pad_rows=3, n_pad_cols=3, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = dense_block_periodic_conv(x, 3, 32, (4,4), strides=(1,1),
                                n_pad_rows=3, n_pad_cols=3, activation='gelu')
  x = MaxPooling2D((2,2), padding='same')(x)

  
  # 16 x 16
  x = periodic_convolution(x, 32, (2,2), strides=(1,1),
                           n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = dense_block_periodic_conv(x, 3, 32, (2,2), strides=(1,1),
                                n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = MaxPooling2D((2,2))(x)

  # 8 x 8
  x = periodic_convolution(x, 32, (2,2), strides=(1,1), 
                           n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = dense_block_periodic_conv(x, 3, 32, (2,2), strides=(1,1),
                                n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = MaxPooling2D((2,1))(x)

  
  # 4 x 8 
  x = periodic_convolution(x, 32, (2,2), strides=(1,1), 
                           n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = BatchNormalization()(x)
  x = Activation('gelu')(x)
  x = dense_block_periodic_conv(x, 3, 32, (2,2), strides=(1,1),
                                n_pad_rows=1, n_pad_cols=1, activation='gelu')

  # Embedding
  encoded_final_feature_maps = periodic_convolution(x, encoded_dim // 32, (2,2), strides=(1,1), 
                                                    n_pad_rows=1, n_pad_cols=1, activation='gelu')
  x = BatchNormalization()(encoded_final_feature_maps)
  x = Activation('gelu')(x)

  # create two decoder blocks if also returning decoder
  if return_encoder_decoder == True:
    input_decoder = Input(shape=(*x.shape[1:],))
    decoder_inputs = [x, input_decoder]
    encoder_model = Model(input_vort, x)
  else:
    decoder_inputs = [x]
  decoder_outputs = []

  for decoder_input in decoder_inputs:
    # starting at 4 x 8 x m // 32
    x = UpSampling2D((2,1))(decoder_input)
    x = periodic_convolution(x, 32, (2,2), strides=(1,1), 
                             n_pad_rows=1, n_pad_cols=1, activation='gelu')
    x = BatchNormalization()(x)
    x = Activation('gelu')(x)
    x = dense_block_periodic_conv(x, 3, 32, (2,2), strides=(1,1),
                                n_pad_rows=1, n_pad_cols=1, activation='gelu')

    # now at 8 x 8 x ? 
    x = UpSampling2D((2,2))(x)
    x = periodic_convolution(x, 32, (2,2), strides=(1,1), 
                             n_pad_rows=1, n_pad_cols=1, activation='gelu')
    x = BatchNormalization()(x)
    x = Activation('gelu')(x)
    x = dense_block_periodic_conv(x, 3, 32, (2,2), strides=(1,1),
                                n_pad_rows=1, n_pad_cols=1, activation='gelu')

    # now at 16 x 16
    x = UpSampling2D((2,2))(x)
    x = periodic_convolution(x, 32, (4,4), strides=(1,1), 
                             n_pad_rows=3, n_pad_cols=3, activation='gelu')
    x = BatchNormalization()(x)
    x = Activation('gelu')(x)
    x = dense_block_periodic_conv(x, 3, 32, (4,4), strides=(1,1),
                                n_pad_rows=3, n_pad_cols=3, activation='gelu')
    
    # now at 32 x 32
    x = UpSampling2D((2,2))(x)
    x = periodic_convolution(x, 32, (4,4), strides=(1,1), 
                             n_pad_rows=3, n_pad_cols=3, activation='gelu')
    x = BatchNormalization()(x)
    x = Activation('gelu')(x)
    x = dense_block_periodic_conv(x, 3, 32, (4,4), strides=(1,1),
                                n_pad_rows=3, n_pad_cols=3, activation='gelu')
    
    # now at 64 x 64
    x = UpSampling2D((2,2))(x)
    x = periodic_convolution(x, 32, (8,8), strides=(1,1), 
                             n_pad_rows=7, n_pad_cols=7, activation='gelu')
    x = BatchNormalization()(x)
    x = Activation('gelu')(x)
    x = dense_block_periodic_conv(x, 3, 32, (8,8), strides=(1,1),
                                n_pad_rows=7, n_pad_cols=7, activation='gelu')

    # return to original configuration 
    x = periodic_convolution(x, 1, (8,8), strides=(1,1), n_pad_rows=7, n_pad_cols=7, activation='tanh')
    decoder_outputs.append(x)
  
  if return_encoder_decoder == True:
    return Model(input_vort, decoder_outputs[0]), encoder_model, Model(decoder_inputs[1], decoder_outputs[1])
  else:
    return Model(input_vort, decoder_outputs[0])

def residual_block_periodic_conv(x, n_filters,
                                 kernel=(1,1), strides=(1,1),
                                 n_pad_rows=1, n_pad_cols=1,
                                 activation='gelu'):
  layer_input = x 

  # number of filters must match input = x.shape[-1]
  n_filters = x.shape[-1]

  x = BatchNormalization()(x)
  x = Activation(activation)(x)

  x = periodic_convolution(x, n_filters, kernel, strides=strides,
                           n_pad_rows=n_pad_rows, n_pad_cols=n_pad_cols, activation=activation)
  
  x = BatchNormalization()(x)

  x = periodic_convolution(x, n_filters, kernel, strides=strides,
                           n_pad_rows=n_pad_rows, n_pad_cols=n_pad_cols, activation='linear')

  x = keras.layers.add([x, layer_input])
  return x

def super_res_v0(Nx_coarse, Ny_coarse, N_filters, N_grow=4, input_channels=1):
  """ Build a model to perform super-resolution, scaling up N_grow times.  """
  input_vort = Input(shape=(Nx_coarse, Ny_coarse, input_channels))
   
  # an initial linear layer prior to Residual blocks 
  x = periodic_convolution(input_vort, N_filters, kernel=(4, 4),
                           n_pad_rows=3, n_pad_cols=3, activation='linear')
  
  # upsample and apply residual block however many times we need to rescale 
  # note we are keeping our kernel constant size -- perhaps not ideal
  # might want to scale this too 
  for _ in range(N_grow):
    x = UpSampling2D((2,2))(x)
    x = residual_block_periodic_conv(x, N_filters, kernel=(4,4),
                                     n_pad_rows=3, n_pad_cols=3)
  
  x = periodic_convolution(x, input_channels, kernel=(4, 4),
                           n_pad_rows=3, n_pad_cols=3, activation='linear')
  return Model(input_vort, x)

def leray_projection(fields, eps=1e-8):
  batch_size, Nx, Ny, _ = fields.shape
  dx = 2 * jnp.pi / Nx 
  dy = 2 * jnp.pi / Ny

  fields_rft = jnp.fft.rfftn(fields, axes=(1,2))
  u_rft = fields_rft[..., 0]
  v_rft = fields_rft[..., 1]

  all_kx = 2 * jnp.pi * jnp.fft.fftfreq(Nx, dx)
  all_ky = 2 * jnp.pi * jnp.fft.rfftfreq(Ny, dy)
  
  kx_mesh, ky_mesh = jnp.meshgrid(all_kx, all_ky)
  kx_mesh = jnp.repeat(
    (kx_mesh.T)[jnp.newaxis, ..., jnp.newaxis],
    repeats=batch_size, 
    axis=0)
  ky_mesh = jnp.repeat(
    (ky_mesh.T)[jnp.newaxis, ..., jnp.newaxis],
    repeats=batch_size,
    axis=0)

  # (1) compute divergence 
  ikxu = 1j * kx_mesh * u_rft[..., jnp.newaxis]
  ikyv = 1j * ky_mesh * v_rft[..., jnp.newaxis]
  div_u_rft = ikxu + ikyv

  # (2) solve Poisson problem 
  phi_rft = - div_u_rft / (eps + kx_mesh ** 2 + ky_mesh ** 2)

  # (3) take grad into channels
  u_correct_ft = -jnp.concatenate([1j * kx_mesh * phi_rft,
                                   1j * ky_mesh * phi_rft], axis=-1)
  u_correction = jnp.fft.irfftn(u_correct_ft, axes=(1,2))
  return fields + u_correction

# objective is make div-func pre-compiled to avoid rebuild every batch
def div_free_2D_layer(u_in):
  """" Custom layer to project onto divergence-free solution via Leray:
          u_out = u_in - grad( nab^{-1} div(u_in) )
       Expected shape is (None, Nx, Ny, 2) """
  if len(u_in.shape) != 4:
    raise ValueError("Expected 4D input, input has shape", u_in.shape)
  if u_in.shape[-1] != 2:
    raise ValueError("Expected 2 channels (2D vel field) but input has ",
                     u_in.shape[-1],
                     "channels.")
  # output shape does not include batch dim -- check
  u_projected = Lambda(leray_projection, 
                       output_shape=u_in.shape[1:])(u_in)
  return u_projected

def exponential_filter(fields):
  batch_size, Nx, Ny, _ = fields.shape
  dx = 2 * jnp.pi / Nx 
  dy = 2 * jnp.pi / Ny

  fields_rft = jnp.fft.rfftn(fields, axes=(1,2))

  all_kx = 2 * jnp.pi * jnp.fft.fftfreq(Nx, dx)
  all_ky = 2 * jnp.pi * jnp.fft.rfftfreq(Ny, dy)
  
  kx_mesh, ky_mesh = jnp.meshgrid(all_kx, all_ky)
  kx_mesh = jnp.repeat(
    (kx_mesh.T)[jnp.newaxis, ..., jnp.newaxis],
    repeats=batch_size, 
    axis=0)
  ky_mesh = jnp.repeat(
    (ky_mesh.T)[jnp.newaxis, ..., jnp.newaxis],
    repeats=batch_size,
    axis=0)
  
  # following Dresdner et al filter exp(- alpha | k / k_max | ^ 2p | ); p = 32, alpha = 6
  k_all = jnp.sqrt(kx_mesh ** 2 + ky_mesh ** 2)
  k_max = jnp.max(k_all)
  filter_exp = jnp.exp( -6 * (k_all / k_max) ** 64)

  # filter field and invert
  filtered_field = fields_rft * filter_exp
  
  return jnp.fft.irfftn(filtered_field, axes=(1,2))

# exp filter layer
def exp_filter_layer(u_in):
  """" Custom layer to apply exponential filter """
  u_projected = Lambda(exponential_filter, 
                       output_shape=u_in.shape[1:])(u_in)
  return u_projected

def super_res_vel_v1(Nx_coarse, Ny_coarse, N_filters, N_grow=4, input_channels=2):
  """ Build a model to perform super-resolution on VELOCITY DATA, 
      scaling up N_grow times.  """
  input_vort = Input(shape=(Nx_coarse, Ny_coarse, input_channels))
   
  # an initial linear layer prior to Residual blocks 
  x = periodic_convolution(input_vort, N_filters, kernel=(4, 4),
                           n_pad_rows=3, n_pad_cols=3, activation='linear')
  
  # upsample and apply residual block however many times we need to rescale 
  # note we are keeping our kernel constant size -- perhaps not ideal
  # might want to scale this too 
  for _ in range(N_grow):
    x = UpSampling2D((2,2))(x)
    x = residual_block_periodic_conv(x, N_filters, kernel=(4,4),
                                     n_pad_rows=3, n_pad_cols=3)
  
  x = periodic_convolution(x, input_channels, kernel=(4, 4),
                           n_pad_rows=3, n_pad_cols=3, activation='linear')
  # project out non-solenoidal component
  x = div_free_2D_layer(x)
  return Model(input_vort, x)

def super_res_vel_v2(Nx_coarse, Ny_coarse, N_filters, N_grow=4, input_channels=2):
  """ Build a model to perform super-resolution on VELOCITY DATA, 
      scaling up N_grow times.  
      Change vs v1: increasing kernel size as we go up
  """
  input_vort = Input(shape=(Nx_coarse, Ny_coarse, input_channels))
   
  # an initial linear layer prior to Residual blocks 
  x = periodic_convolution(input_vort, N_filters, kernel=(4, 4),
                           n_pad_rows=3, n_pad_cols=3, activation='linear')
  
  # upsample and apply residual block however many times we need to rescale 
  # note we are keeping our kernel constant size -- perhaps not ideal
  # might want to scale this too 
  for n in range(N_grow):
    kern_width = 2 ** (2 + n)
    x = UpSampling2D((2,2))(x)
    x = residual_block_periodic_conv(x, 
                                     N_filters, 
                                     kernel=(kern_width,kern_width),
                                     n_pad_rows=kern_width-1, 
                                     n_pad_cols=kern_width-1)
  
  x = periodic_convolution(x, input_channels, kernel=(16, 16),
                           n_pad_rows=15, n_pad_cols=15, activation='linear')
  # project out non-solenoidal component
  if input_channels == 2:
    x = div_free_2D_layer(x)
  x = exp_filter_layer(x)
  return Model(input_vort, x)